#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auth 数据库备份脚本
功能:
1. 从服务器下载 auth.db 到本地
2. 按日期目录存放备份，保留历史版本
3. 支持 SCP/RSYNC 两种传输方式
"""
import re
import os
import sys
import json
import argparse
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
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
    "server_user": "root",
    "server_host": "149.104.30.138",
    "server_port": 22,
    "server_auth_db": "/opt/zsxq-reader/auth.db",
    "local_backup_base_dir": "E:/Documents/auth备份",
    "ssh_key_path": None,
    "max_backups": 30,  # 最多保留多少天的备份
}


def convert_windows_to_cygwin(windows_path: str) -> str:
    """将 Windows 路径转换为 Cygwin/rsync 路径格式"""
    path = windows_path.replace("\\", "/")
    if len(path) >= 2 and path[1] == ':':
        drive = path[0].lower()
        rest = path[2:]
        return f"/cygdrive/{drive}{rest}"
    return path


class AuthDBBackupManager:
    """Auth 数据库备份管理器"""

    def __init__(self, config: dict):
        self.config = config
        self.server_user = config["server_user"]
        self.server_host = config["server_host"]
        self.server_port = config["server_port"]
        self.server_auth_db = config["server_auth_db"]
        self.ssh_key = config.get("ssh_key_path")
        
        # 本地备份根目录
        backup_base = config.get("local_backup_base_dir", "E:/Documents/auth备份")
        self.backup_base_dir = Path(backup_base)
        
        # 当天日期目录
        today = datetime.now().strftime("%Y-%m-%d")
        self.today_backup_dir = self.backup_base_dir / today
        
        # 最大备份数
        self.max_backups = config.get("max_backups", 30)

    def build_scp_command(self) -> list:
        """构建 SCP 下载命令"""
        cmd = ["scp"]
        
        # SSH 端口
        cmd.extend(["-P", str(self.server_port)])
        
        # SSH 密钥（如果有）
        if self.ssh_key and os.path.exists(self.ssh_key):
            cmd.extend(["-i", self.ssh_key])
        
        # StrictHostKeyChecking 关闭（避免首次连接提示）
        cmd.extend(["-o", "StrictHostKeyChecking=no"])
        cmd.extend(["-o", "UserKnownHostsFile=NUL"])
        
        # 远程路径
        remote_path = f"{self.server_user}@{self.server_host}:{self.server_auth_db}"
        cmd.append(remote_path)
        
        # 本地目标路径（先下载到临时文件）
        local_temp = str(self.today_backup_dir / "auth.db.tmp")
        cmd.append(local_temp)
        
        return cmd, local_temp

    def build_rsync_command(self) -> tuple:
        """构建 rsync 下载命令"""
        source = f"{self.server_user}@{self.server_host}:{self.server_auth_db}"
        
        # 本地临时目标（cygwin 格式）
        local_temp_path = self.today_backup_dir / "auth.db.tmp"
        dest = convert_windows_to_cygwin(str(local_temp_path.resolve()))
        
        cmd_parts = [
            "rsync",
            "-avz",
            "--progress",
            '-e', f"ssh -p {self.server_port}",
            source,
            dest
        ]
        
        return " ".join(cmd_parts), str(local_temp_path)

    def cleanup_old_backups(self):
        """清理超出保留天数的旧备份"""
        if not self.backup_base_dir.exists():
            return

        # 获取所有日期目录并按名称排序
        date_dirs = []
        for d in self.backup_base_dir.iterdir():
            if d.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}", d.name):
                date_dirs.append(d)

        date_dirs.sort(key=lambda x: x.name, reverse=True)

        # 删除超出的旧备份
        if len(date_dirs) > self.max_backups:
            for old_dir in date_dirs[self.max_backups:]:
                try:
                    shutil.rmtree(old_dir)
                    logger.info(f"🗑️  已清理旧备份: {old_dir.name}")
                except Exception as e:
                    logger.warning(f"清理失败 {old_dir.name}: {e}")

    def backup(self, method: str = "scp", dry_run: bool = False) -> bool:
        """执行备份"""

        logger.info("=" * 60)
        logger.info("🔄 开始备份 Auth 数据库")
        logger.info("=" * 60)
        logger.info(f"   服务器: {self.server_user}@{self.server_host}:{self.server_port}")
        logger.info(f"   远程路径: {self.server_auth_db}")
        logger.info(f"   本地目录: {self.today_backup_dir}")
        logger.info(f"   传输方式: {method.upper()}")

        if dry_run:
            logger.info("🔍 干跑模式，不实际执行")
            return True

        # 创建当天备份目录
        self.today_backup_dir.mkdir(parents=True, exist_ok=True)

        # 如果今天已经有最终备份文件，先删除临时文件（如果存在）
        final_path = self.today_backup_dir / "auth.db"
        temp_path = self.today_backup_dir / "auth.db.tmp"

        # 构建命令
        if method.lower() == "rsync":
            cmd_str, temp_file = self.build_rsync_command()
            logger.info(f"执行命令: {cmd_str}")
            
            try:
                result = subprocess.run(
                    cmd_str,
                    shell=True,
                    text=True,
                    cwd=str(Path(__file__).parent)
                )
                
                if result.returncode != 0:
                    logger.error(f"❌ rsync 备份失败，返回码: {result.returncode}")
                    return False
                    
            except FileNotFoundError:
                logger.warning("⚠️  rsync 未找到，回退到 SCP 方式")
                cmd_list, temp_file = self.build_scp_command()
                result = subprocess.run(cmd_list, text=True)
                if result.returncode != 0:
                    logger.error(f"❌ SCP 备份失败，返回码: {result.returncode}")
                    return False
                    
        else:
            # 默认使用 SCP
            cmd_list, temp_file = self.build_scp_command()
            logger.info(f"执行命令: {' '.join(cmd_list)}")
            
            try:
                result = subprocess.run(cmd_list, text=True)
                
                if result.returncode != 0:
                    logger.error(f"❌ SCP 备份失败，返回码: {result.returncode}")
                    return False
                    
            except Exception as e:
                logger.error(f"❌ 备份异常: {e}")
                return False

        # 检查临时文件是否存在
        if not Path(temp_file).exists():
            logger.error("❌ 下载完成但临时文件不存在")
            return False

        # 获取文件大小
        file_size = Path(temp_file).stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        
        # 如果已存在最终文件，删除它再重命名
        if final_path.exists():
            final_path.unlink()
        
        # 重命名为最终文件名
        Path(temp_file).rename(final_path)
        
        logger.info(f"✅ 备份成功: {final_path} ({file_size_mb:.2f} MB)")

        # 清理旧备份
        self.cleanup_old_backups()

        return True

    def list_backups(self):
        """列出所有备份"""
        logger.info("=" * 60)
        logger.info("📋 Auth 数据库备份列表")
        logger.info("=" * 60)

        if not self.backup_base_dir.exists():
            logger.info("备份目录不存在")
            return

        date_dirs = sorted(
            [d for d in self.backup_base_dir.iterdir() 
             if d.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}", d.name)],
            reverse=True
        )

        if not date_dirs:
            logger.info("暂无备份")
            return

        for d in date_dirs:
            db_file = d / "auth.db"
            if db_file.exists():
                size = db_file.stat().st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(db_file.stat().st_mtime)
                logger.info(f"   📦 {d.name}  ({size:.2f} MB, 修改时间: {mtime:%H:%M:%S})")
            else:
                logger.info(f"   📁 {d.name}  (无数据库文件)")


def main():
    parser = argparse.ArgumentParser(
        description="Auth 数据库备份工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 执行备份（SCP）
  python auth_db_backup.py
  
  # 使用 rsync 备份
  python auth_db_backup.py --method rsync
  
  # 干跑测试
  python auth_db_backup.py --dry-run
  
  # 查看所有备份
  python auth_db_backup.py --list
  
  # 自定义本地备份目录
  python auth_db_backup.py --backup-dir "E:/my backups/auth"
  
  # 指定配置文件
  python auth_db_backup.py --config sync_config.json
        """
    )

    parser.add_argument("--config", default="sync_config.json",
                        help="配置文件路径 (默认: sync_config.json)")
    parser.add_argument("-m", "--method", choices=["scp", "rsync"], default="scp",
                        help="传输方式 (默认: scp)")
    parser.add_argument("-d", "--backup-dir",
                        help="自定义本地备份根目录")
    parser.add_argument("--max-backups", type=int, default=30,
                        help="最大保留备份数量 (默认: 30)")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="干跑模式（只显示将执行的操作）")
    parser.add_argument("-l", "--list", action="store_true",
                        help="列出所有已有备份")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="详细输出")

    args = parser.parse_args()

    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 加载配置
    config = DEFAULT_CONFIG.copy()
    config_path = Path(args.config)

    # 配置文件相对于本脚本所在目录
    if not config_path.is_absolute():
        config_path = Path(__file__).parent / config_path

    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
            config.update(user_config)
            logger.info(f"加载配置文件: {config_path}")
    else:
        logger.warning(f"配置文件不存在: {config_path}, 使用默认配置")

    # 命令行参数覆盖配置
    if args.backup_dir:
        config["local_backup_base_dir"] = args.backup_dir
    if args.max_backups:
        config["max_backups"] = args.max_backups

    # 创建备份管理器
    manager = AuthDBBackupManager(config)

    try:
        if args.list:
            manager.list_backups()
        else:
            success = manager.backup(method=args.method, dry_run=args.dry_run)
            if not success:
                sys.exit(1)

    except KeyboardInterrupt:
        logger.warning("\n⚠️  用户中断操作")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ 执行失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
