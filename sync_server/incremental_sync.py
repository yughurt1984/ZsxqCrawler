#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量数据库同步脚本 - 基于时间戳字段
功能:
1. 自动检测数据库表的时间戳字段 (created_at, imported_at, updated_at, modify_time)
2. 记录每个表的最后同步时间
3. 只同步新增或修改的记录
4. 使用 SSH + SQL 方式同步,INSERT OR REPLACE 覆盖服务器数据
"""

import os
import sys
import json
import sqlite3
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import logging

# =========================
# 日志配置
# =========================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# =========================
# 配置
# =========================

DEFAULT_CONFIG = {
    "local_base_dir": "../output/databases",  # ← 改为相对路径
    "local_auth_db": "../auth.db",  # ← 改为相对路径
    "server_user": "root",
    "server_host": "149.104.30.138",
    "server_port": 22,
    "server_base_dir": "/opt/zsxq-reader/output/databases",
    "server_auth_db": "/opt/zsxq-reader/auth.db",
    "sync_state_db": "sync_state.db",
    "batch_size": 1000,
    "temp_dir": "temp",  # ← 改为 Windows 兼容路径
    "ssh_key_path": None,
}


class SyncStateManager:
    """同步状态管理器 - 记录每个表的最后同步时间"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._init_database()
    
    def _init_database(self):
        """初始化同步状态表"""
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                database_type TEXT NOT NULL,
                group_id TEXT,
                table_name TEXT NOT NULL,
                last_sync_time TEXT NOT NULL,
                last_sync_count INTEGER DEFAULT 0,
                last_sync_at TEXT NOT NULL,
                UNIQUE(database_type, group_id, table_name)
            )
        ''')
        
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sync_state 
            ON sync_state(database_type, group_id, table_name)
        ''')
        
        self.conn.commit()
    
    def get_last_sync_time(self, database_type: str, group_id: str, table_name: str) -> Optional[str]:
        """获取指定表的最后同步时间"""
        self.cursor.execute('''
            SELECT last_sync_time 
            FROM sync_state 
            WHERE database_type = ? AND group_id = ? AND table_name = ?
        ''', (database_type, group_id, table_name))
        
        row = self.cursor.fetchone()
        return row[0] if row else None
    
    def update_sync_state(self, database_type: str, group_id: str, table_name: str, 
                          last_sync_time: str, sync_count: int):
        """更新同步状态"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO sync_state 
            (database_type, group_id, table_name, last_sync_time, last_sync_count, last_sync_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (database_type, group_id, table_name, last_sync_time, sync_count, 
              datetime.now().isoformat()))
        
        self.conn.commit()
        logger.info(f"更新同步状态: {database_type}/{group_id}/{table_name} -> {last_sync_time}")
    
    def get_all_sync_states(self) -> List[Dict]:
        """获取所有同步状态"""
        self.cursor.execute('''
            SELECT database_type, group_id, table_name, last_sync_time, 
                   last_sync_count, last_sync_at
            FROM sync_state
            ORDER BY last_sync_at DESC
        ''')
        
        states = []
        for row in self.cursor.fetchall():
            states.append({
                'database_type': row[0],
                'group_id': row[1],
                'table_name': row[2],
                'last_sync_time': row[3],
                'last_sync_count': row[4],
                'last_sync_at': row[5]
            })
        
        return states
    
    def clear_all_states(self):
        """清空所有同步状态"""
        self.cursor.execute("DELETE FROM sync_state")
        self.conn.commit()
        logger.info("已清空所有同步状态")
    
    def close(self):
        """关闭数据库连接"""
        self.conn.close()


class DatabaseSchemaAnalyzer:
    """数据库结构分析器 - 自动检测时间戳字段"""
    
    TIMESTAMP_FIELDS = ['updated_at', 'imported_at', 'created_at', 'modify_time']
    
    @staticmethod
    def get_tables(db_path: str) -> List[str]:
        """获取数据库中的所有表名"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return tables
    
    @staticmethod
    def get_table_schema(db_path: str, table_name: str) -> Dict[str, str]:
        """获取表结构 (字段名 -> 类型)"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        conn.close()
        return columns
    
    @staticmethod
    def find_timestamp_field(db_path: str, table_name: str) -> Optional[str]:
        """查找表中的时间戳字段"""
        columns = DatabaseSchemaAnalyzer.get_table_schema(db_path, table_name)
        
        # 优先级: updated_at > imported_at > created_at > modify_time
        for field in DatabaseSchemaAnalyzer.TIMESTAMP_FIELDS:
            if field in columns:
                return field
        
        return None
    
    @staticmethod
    def get_table_columns(db_path: str, table_name: str) -> List[str]:
        """获取表的所有列名"""
        columns = DatabaseSchemaAnalyzer.get_table_schema(db_path, table_name)
        return list(columns.keys())


class IncrementalSyncManager:
    """增量同步管理器"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.local_base = Path(config["local_base_dir"])
        self.sync_state = SyncStateManager(config["sync_state_db"])
        self.temp_dir = Path(config.get("temp_dir", "/tmp/zsxq_sync"))
        
        # 创建临时目录
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 统计信息
        self.stats = {
            "databases_processed": 0,
            "tables_processed": 0,
            "records_synced": 0,
            "errors": [],
            "skipped_tables": 0
        }
    
    def get_new_records(self, db_path: str, table_name: str, 
                        timestamp_field: str, last_sync_time: Optional[str]) -> List[Dict]:
        """获取新增或修改的记录"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 获取所有列名
        column_names = DatabaseSchemaAnalyzer.get_table_columns(db_path, table_name)
        
        # 构建查询
        if last_sync_time:
            query = f'''
                SELECT * FROM {table_name}
                WHERE {timestamp_field} > ?
                ORDER BY {timestamp_field} ASC
            '''
            cursor.execute(query, (last_sync_time,))
        else:
            # 首次同步,获取所有记录
            query = f'''
                SELECT * FROM {table_name}
                ORDER BY {timestamp_field} ASC
            '''
            cursor.execute(query)
        
        # 转换为字典列表
        records = []
        for row in cursor.fetchall():
            record = {column_names[i]: row[i] for i in range(len(column_names))}
            records.append(record)
        
        conn.close()
        return records
    
    def generate_sql_statements(self, records: List[Dict], table_name: str) -> List[str]:
        """生成 SQL INSERT OR REPLACE 语句"""
        sql_statements = []
        
        for record in records:
            # 构建 INSERT OR REPLACE 语句
            columns = list(record.keys())
            values = []
            
            for col in columns:
                val = record[col]
                if val is None:
                    values.append("NULL")
                elif isinstance(val, (int, float)):
                    values.append(str(val))
                else:
                    # 转义单引号
                    val_str = str(val).replace("'", "''")
                    values.append(f"'{val_str}'")
            
            columns_str = ', '.join(columns)
            values_str = ', '.join(values)
            
            sql = f"INSERT OR REPLACE INTO {table_name} ({columns_str}) VALUES ({values_str});"
            sql_statements.append(sql)
        
        return sql_statements
    
    def execute_remote_sql(self, sql_statements: List[str], table_name: str, 
                           server_db_path: str) -> bool:
        """通过 SSH 执行远程 SQL 语句"""
        if not sql_statements:
            return True
        
        # 分批处理
        batch_size = self.config.get("batch_size", 1000)
        total_statements = len(sql_statements)
        
        for i in range(0, total_statements, batch_size):
            batch = sql_statements[i:i+batch_size]
            
            # 保存到临时文件
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            temp_file = self.temp_dir / f"sync_{table_name}_{timestamp}_{i//batch_size}.sql"
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(batch))
            
            logger.info(f"生成SQL文件: {temp_file.name} ({len(batch)} 条语句)")
            
            # 上传到服务器
            server_user = self.config["server_user"]
            server_host = self.config["server_host"]
            server_port = self.config["server_port"]
            ssh_key_path = self.config.get("ssh_key_path")
            
            remote_file = f"/tmp/sync_{table_name}_{timestamp}.sql"
            
            # 构建 SCP 命令
            upload_cmd = ["scp", "-P", str(server_port)]
            if ssh_key_path:
                upload_cmd.extend(["-i", ssh_key_path])
            upload_cmd.extend([str(temp_file), f"{server_user}@{server_host}:{remote_file}"])
            
            result = subprocess.run(upload_cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                logger.error(f"上传失败: {result.stderr}")
                self.stats["errors"].append(f"{table_name}: 上传失败 - {result.stderr}")
                return False
            
            # 构建 SSH 命令
            ssh_cmd = ["ssh", "-p", str(server_port)]
            if ssh_key_path:
                ssh_cmd.extend(["-i", ssh_key_path])
            ssh_cmd.extend([
                f"{server_user}@{server_host}",
                f"sqlite3 {server_db_path} < {remote_file} && rm {remote_file}"
            ])
            
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
            
            # 清理本地临时文件
            temp_file.unlink()
            
            if result.returncode != 0:
                logger.error(f"执行失败: {result.stderr}")
                self.stats["errors"].append(f"{table_name}: 执行失败 - {result.stderr}")
                return False
            
            logger.info(f"成功执行批次 {i//batch_size + 1}/{(total_statements-1)//batch_size + 1}")
        
        return True
    
    def sync_table_to_server(self, db_path: str, table_name: str, 
                             database_type: str, group_id: str,
                             server_db_path: str) -> int:
        """同步单个表到服务器"""
        # 1. 检测时间戳字段
        timestamp_field = DatabaseSchemaAnalyzer.find_timestamp_field(db_path, table_name)
        
        if not timestamp_field:
            logger.info(f"跳过表 {table_name}: 没有时间戳字段")
            self.stats["skipped_tables"] += 1
            return 0
        
        # 2. 获取最后同步时间
        last_sync_time = self.sync_state.get_last_sync_time(
            database_type, group_id, table_name
        )
        
        if last_sync_time:
            logger.info(f"最后同步时间: {last_sync_time}")
        else:
            logger.info(f"首次同步表 {table_name}")
        
        # 3. 获取新记录
        new_records = self.get_new_records(db_path, table_name, timestamp_field, last_sync_time)
        
        if not new_records:
            logger.info(f"表 {table_name}: 无新数据")
            return 0
        
        logger.info(f"表 {table_name}: 发现 {len(new_records)} 条新记录")
        
        # 4. 生成SQL语句
        sql_statements = self.generate_sql_statements(new_records, table_name)
        
        # 5. 执行远程同步
        if self.execute_remote_sql(sql_statements, table_name, server_db_path):
            # 6. 更新同步状态
            max_timestamp = max(
                r[timestamp_field] for r in new_records 
                if r.get(timestamp_field) is not None
            )
            
            self.sync_state.update_sync_state(
                database_type, group_id, table_name, 
                str(max_timestamp), len(new_records)
            )
            
            logger.info(f"✅ 成功同步 {len(new_records)} 条记录")
            return len(new_records)
        else:
            logger.error(f"❌ 同步失败")
            return 0
    
    def sync_database(self, local_db_path: str, server_db_path: str, 
                      database_type: str, group_id: str = None):
        """同步单个数据库文件"""
        logger.info("="*60)
        logger.info(f"📦 同步数据库: {Path(local_db_path).name}")
        logger.info(f"   类型: {database_type} | 群组: {group_id or '全局'}")
        logger.info("="*60)
        
        if not Path(local_db_path).exists():
            logger.error(f"数据库文件不存在: {local_db_path}")
            return
        
        # 获取所有表
        tables = DatabaseSchemaAnalyzer.get_tables(local_db_path)
        logger.info(f"📋 发现 {len(tables)} 个表")
        
        # 同步每个表
        for table_name in tables:
            if table_name.startswith('sqlite_'):  # 跳过SQLite系统表
                continue
            
            logger.info(f"\n🔄 同步表: {table_name}")
            
            try:
                synced = self.sync_table_to_server(
                    local_db_path, table_name, 
                    database_type, group_id or 'global',
                    server_db_path
                )
                
                self.stats["tables_processed"] += 1
                self.stats["records_synced"] += synced
                
            except Exception as e:
                logger.error(f"同步失败: {e}", exc_info=True)
                self.stats["errors"].append(f"{table_name}: {str(e)}")
        
        self.stats["databases_processed"] += 1
    
    def sync_all_groups(self):
        """同步所有群组的数据库"""
        logger.info("="*60)
        logger.info("🚀 开始增量同步 - 所有群组")
        logger.info("="*60)
        
        # 遍历所有群组目录
        if not self.local_base.exists():
            logger.warning(f"本地数据库目录不存在: {self.local_base}")
            return
        
        for group_dir in self.local_base.iterdir():
            if group_dir.is_dir() and group_dir.name.isdigit():
                self.sync_group(group_dir.name)
        
        # 同步认证数据库
        self.sync_auth_database()
    
    def sync_group(self, group_id: str):
        """同步单个群组的数据库"""
        group_dir = self.local_base / group_id
        
        if not group_dir.exists():
            logger.warning(f"群组目录不存在: {group_dir}")
            return
        
        # 同步话题数据库
        topics_db = group_dir / f"zsxq_topics_{group_id}.db"
        if topics_db.exists():
            server_db = f"{self.config['server_base_dir']}/{group_id}/zsxq_topics_{group_id}.db"
            self.sync_database(str(topics_db), server_db, "topics", group_id)
        
        # 同步文件数据库
        files_db = group_dir / f"zsxq_files_{group_id}.db"
        if files_db.exists():
            server_db = f"{self.config['server_base_dir']}/{group_id}/zsxq_files_{group_id}.db"
            self.sync_database(str(files_db), server_db, "files", group_id)
        
        # 同步专栏数据库
        columns_db = group_dir / f"zsxq_columns_{group_id}.db"
        if columns_db.exists():
            server_db = f"{self.config['server_base_dir']}/{group_id}/zsxq_columns_{group_id}.db"
            self.sync_database(str(columns_db), server_db, "columns", group_id)
    
    def sync_auth_database(self):
        """同步认证数据库"""
        auth_db = self.config["local_auth_db"]
        
        if not Path(auth_db).exists():
            logger.warning(f"认证数据库不存在: {auth_db}")
            return
        
        server_auth_db = self.config["server_auth_db"]
        self.sync_database(auth_db, server_auth_db, "auth", None)
    
    def init_sync_state_from_local(self):
        """从本地数据库初始化同步状态(服务器已有数据)"""
        logger.info("="*60)
        logger.info("🔧 初始化同步状态 - 从本地数据库")
        logger.info("="*60)
        
        if not self.local_base.exists():
            logger.warning(f"本地数据库目录不存在: {self.local_base}")
            return
        
        for group_dir in self.local_base.iterdir():
            if group_dir.is_dir() and group_dir.name.isdigit():
                self._init_group_sync_state(group_dir.name)
        
        logger.info("✅ 同步状态初始化完成")


    def _init_group_sync_state(self, group_id: str):
        """初始化单个群组的同步状态"""
        group_dir = self.local_base / group_id
        
        topics_db = group_dir / f"zsxq_topics_{group_id}.db"
        if topics_db.exists():
            self._init_database_sync_state(str(topics_db), "topics", group_id)
        
        files_db = group_dir / f"zsxq_files_{group_id}.db"
        if files_db.exists():
            self._init_database_sync_state(str(files_db), "files", group_id)
        
        columns_db = group_dir / f"zsxq_columns_{group_id}.db"
        if columns_db.exists():
            self._init_database_sync_state(str(columns_db), "columns", group_id)


    def _init_database_sync_state(self, db_path: str, database_type: str, group_id: str):
        """初始化单个数据库的同步状态"""
        logger.info(f"\n📦 处理数据库: {Path(db_path).name}")
        
        tables = DatabaseSchemaAnalyzer.get_tables(db_path)
        
        for table_name in tables:
            if table_name.startswith('sqlite_'):
                continue
            
            timestamp_field = DatabaseSchemaAnalyzer.find_timestamp_field(db_path, table_name)
            
            if not timestamp_field:
                continue
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            try:
                cursor.execute(f"SELECT MAX({timestamp_field}) FROM {table_name}")
                result = cursor.fetchone()
                max_timestamp = result[0] if result and result[0] else None
                
                if max_timestamp:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    
                    self.sync_state.update_sync_state(
                        database_type, group_id, table_name,
                        str(max_timestamp), count
                    )
                    
                    logger.info(f"  ✅ {table_name}: {count} 条记录, 最大时间: {max_timestamp}")
            except Exception as e:
                logger.error(f"  ❌ {table_name}: {e}")
            finally:
                conn.close()


    def backup_auth_from_server(self):
        """从服务器备份认证数据库到本地"""
        logger.info("="*60)
        logger.info("🔐 从服务器备份认证数据库到本地")
        logger.info("="*60)
        
        server_user = self.config["server_user"]
        server_host = self.config["server_host"]
        server_port = self.config["server_port"]
        server_auth_db = self.config["server_auth_db"]
        local_auth_db = self.config["local_auth_db"]
        ssh_key_path = self.config.get("ssh_key_path")
        
        # 1. 备份本地 auth.db
        if Path(local_auth_db).exists():
            backup_path = f"{local_auth_db}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            import shutil
            shutil.copy2(local_auth_db, backup_path)
            logger.info(f"📦 备份本地认证数据库: {backup_path}")
        
        # 2. 从服务器下载
        download_cmd = ["scp", "-P", str(server_port)]
        if ssh_key_path:
            download_cmd.extend(["-i", ssh_key_path])
        download_cmd.extend([f"{server_user}@{server_host}:{server_auth_db}", local_auth_db])
        
        result = subprocess.run(download_cmd, capture_output=True, text=True, check=False)
        
        if result.returncode != 0:
            logger.error(f"下载失败: {result.stderr}")
            return False
        
        logger.info(f"✅ 成功从服务器备份认证数据库")
        return True



    
    def print_summary(self):
        """打印同步摘要"""
        logger.info("="*60)
        logger.info("📊 同步摘要")
        logger.info("="*60)
        logger.info(f"✅ 数据库处理: {self.stats['databases_processed']} 个")
        logger.info(f"✅ 表处理: {self.stats['tables_processed']} 个")
        logger.info(f"⏭️  跳过表: {self.stats['skipped_tables']} 个")
        logger.info(f"✅ 记录同步: {self.stats['records_synced']} 条")
        
        if self.stats["errors"]:
            logger.error(f"❌ 错误数量: {len(self.stats['errors'])}")
            for error in self.stats["errors"][:5]:
                logger.error(f"  - {error}")
        
        # 显示最近的同步状态
        logger.info("\n📋 最近同步状态:")
        states = self.sync_state.get_all_sync_states()
        for state in states[:10]:  # 只显示最近10条
            logger.info(
                f"  - {state['database_type']}/{state['table_name']}: "
                f"{state['last_sync_count']} 条记录, "
                f"最后同步: {state['last_sync_at']}"
            )
    
    def close(self):
        """清理资源"""
        self.sync_state.close()
        
        # 清理临时目录
        if self.temp_dir.exists():
            for temp_file in self.temp_dir.glob("*.sql"):
                temp_file.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="增量数据库同步 - 基于时间戳字段",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 同步所有群组
  python incremental_sync.py
  
  # 同步指定群组
  python incremental_sync.py --group-id 12345
  
  # 只同步认证数据库
  python incremental_sync.py --sync-auth
  
  # 查看同步状态
  python incremental_sync.py --show-state
  
  # 重置同步状态(重新全量同步)
  python incremental_sync.py --reset-state
        """
    )
    
    parser.add_argument("--config", default="sync_config.json",  # ← 改为当前目录
                   help="配置文件路径")
    parser.add_argument("--group-id", help="指定要同步的群组ID(不指定则同步所有)")
    parser.add_argument("--sync-auth", action="store_true", help="同步认证数据库")
    parser.add_argument("--reset-state", action="store_true", help="重置同步状态(重新全量同步)")
    parser.add_argument("--show-state", action="store_true", help="显示当前同步状态")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行(不实际执行)")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    parser.add_argument("--init-sync-state", action="store_true", 
                   help="初始化同步状态(服务器已有数据)")
    parser.add_argument("--backup-auth-from-server", action="store_true", 
                   help="从服务器备份认证数据库到本地")
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 加载配置
    config = DEFAULT_CONFIG.copy()
    if Path(args.config).exists():
        with open(args.config, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
            config.update(user_config)
            logger.info(f"加载配置文件: {args.config}")
    else:
        logger.warning(f"配置文件不存在: {args.config}, 使用默认配置")
    
    # 创建同步管理器
    sync_manager = IncrementalSyncManager(config)
    
    try:
        if args.show_state:
            # 显示同步状态
            states = sync_manager.sync_state.get_all_sync_states()
            print("\n📋 当前同步状态:")
            print("="*80)
            for state in states:
                print(f"数据库: {state['database_type']:<10} | "
                      f"群组: {state['group_id']:<10} | "
                      f"表: {state['table_name']:<20}")
                print(f"  最后同步时间: {state['last_sync_time']} | "
                      f"记录数: {state['last_sync_count']} | "
                      f"同步于: {state['last_sync_at']}")
            return
        
        if args.init_sync_state:
            # 初始化同步状态
            sync_manager.init_sync_state_from_local()
            return
        
        if args.backup_auth_from_server:
            # 从服务器备份认证数据库
            sync_manager.backup_auth_from_server()
            return

        if args.reset_state:
            # 重置同步状态
            print("⚠️  重置同步状态...")
            sync_manager.sync_state.clear_all_states()
            print("✅ 同步状态已重置,下次同步将为全量同步")
            return
        
        if args.dry_run:
            print("⚠️  模拟运行模式 - 不会实际执行同步操作")
            return
        
        # 执行同步
        if args.group_id:
            sync_manager.sync_group(args.group_id)
        elif args.sync_auth:
            sync_manager.sync_auth_database()
        else:
            sync_manager.sync_all_groups()
        
        # 打印摘要
        sync_manager.print_summary()
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️  用户中断同步")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ 同步失败: {e}", exc_info=True)
        sys.exit(1)
    finally:
        sync_manager.close()


if __name__ == "__main__":
    main()
