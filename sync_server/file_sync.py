#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件增量同步脚本 - 使用 rsync
功能:
1. 同步 downloads 和 images 目录
2. 增量同步，只传输新文件
3. 支持干跑模式预览
"""

import os
import sys
import json
import argparse
import subprocess
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
    "local_base_dir": "../output/databases",
    "server_user": "root",
    "server_host": "149.104.30.138",
    "server_port": 22,
    "server_base_dir": "/opt/zsxq-reader/output/databases",
    "ssh_key_path": None,
    "file_sync": {
        "enabled": True,
        "directories": ["downloads", "images"],
        "rsync_path": "rsync",
        "rsync_options": "-avz --progress"
    }
}


def convert_windows_to_cygwin(windows_path: str) -> str:
    """将 Windows 路径转换为 Cygwin/rsync 路径格式
    
    Examples:
        E:\\zsxq\\data -> /cygdrive/e/zsxq/data
        E:/zsxq/data -> /cygdrive/e/zsxq/data
    """
    # 统一使用正斜杠
    path = windows_path.replace("\\", "/")
    
    # 提取盘符
    if len(path) >= 2 and path[1] == ':':
        drive = path[0].lower()
        rest = path[2:]
        return f"/cygdrive/{drive}{rest}"
    
    return path


class FileSyncManager:
    """文件同步管理器 - 使用 rsync"""
    
    def __init__(self, config: dict):
        self.config = config
        self.local_base = Path(config["local_base_dir"])
        self.ssh_key = config.get("ssh_key_path")
        self.server_user = config["server_user"]
        self.server_host = config["server_host"]
        self.server_port = config["server_port"]
        self.server_base = config["server_base_dir"]
        
        # 文件同步配置
        file_sync_config = config.get("file_sync", {})
        self.sync_dirs = file_sync_config.get("directories", ["downloads", "images"])
        self.rsync_path = file_sync_config.get("rsync_path", "rsync")
        self.rsync_options = file_sync_config.get("rsync_options", "-avz")
        
        # 统计
        self.stats = {
            "directories_synced": 0,
            "total_files": 0,
            "total_size": 0,
            "errors": []
        }
    
    def build_rsync_command(self, group_id: str, directory: str, dry_run: bool = False) -> str:
        """构建 rsync 命令（本地 → 服务器上传）"""
        
        # 源路径（本地）- 转换为 cygwin 格式
        local_path = self.local_base / group_id / directory
        local_path.mkdir(parents=True, exist_ok=True)
        source_path = convert_windows_to_cygwin(str(local_path.resolve())) + "/"
        
        # 目标路径（服务器）
        dest_path = f"{self.server_user}@{self.server_host}:{self.server_base}/{group_id}/{directory}/"
        
        # 构建命令字符串
        cmd_parts = [self.rsync_path]
        
        # 添加 rsync 选项
        cmd_parts.append(self.rsync_options)
        
        # 干跑模式
        if dry_run:
            cmd_parts.append("-n")
        
        # SSH 选项 - 简化，不使用密钥
        ssh_cmd = f"ssh -p {self.server_port}"
        cmd_parts.append(f'-e "{ssh_cmd}"')
        
        # 源和目标
        cmd_parts.append(source_path)
        cmd_parts.append(dest_path)
        
        return " ".join(cmd_parts)
    
    def sync_directory(self, group_id: str, directory: str, dry_run: bool = False) -> bool:
        """同步单个目录"""
        
        logger.info("=" * 60)
        logger.info(f"🔄 同步目录: {group_id}/{directory}")
        logger.info("=" * 60)
        
        cmd = self.build_rsync_command(group_id, directory, dry_run)
        
        logger.info(f"执行命令: {cmd}")
        
        try:
            # 不使用 capture_output，让输出直接显示在终端
            result = subprocess.run(
                cmd,
                shell=True,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"同步失败，返回码: {result.returncode}")
                self.stats["errors"].append(f"{group_id}/{directory}: 返回码 {result.returncode}")
                return False
            
            if dry_run:
                logger.info("✅ 干跑测试成功")
            else:
                logger.info(f"✅ 同步完成: {group_id}/{directory}")
                self.stats["directories_synced"] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"同步异常: {e}")
            self.stats["errors"].append(f"{group_id}/{directory}: {str(e)}")
            return False

    
    def sync_group(self, group_id: str, dry_run: bool = False):
        """同步单个群组的文件目录"""
        
        logger.info("=" * 60)
        logger.info(f"🚀 开始同步群组: {group_id}")
        logger.info("=" * 60)
        
        for directory in self.sync_dirs:
            self.sync_directory(group_id, directory, dry_run)
    
    def sync_all_groups(self, dry_run: bool = False):
        """同步所有群组的文件目录"""
        
        logger.info("=" * 60)
        logger.info("🚀 开始文件同步 - 所有群组")
        logger.info("=" * 60)
        
        if not self.local_base.exists():
            logger.warning(f"本地数据库目录不存在: {self.local_base}")
            return
        
        # 遍历所有群组目录
        for group_dir in self.local_base.iterdir():
            if group_dir.is_dir() and group_dir.name.isdigit():
                self.sync_group(group_dir.name, dry_run)
        
        self.print_summary()
    
    def print_summary(self):
        """打印同步摘要"""
        logger.info("=" * 60)
        logger.info("📊 同步摘要")
        logger.info("=" * 60)
        logger.info(f"✅ 目录同步: {self.stats['directories_synced']} 个")
        
        if self.stats["errors"]:
            logger.error(f"❌ 错误数量: {len(self.stats['errors'])}")
            for error in self.stats["errors"]:
                logger.error(f"  - {error}")


def main():
    parser = argparse.ArgumentParser(
        description="文件增量同步 - 使用 rsync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 同步所有群组的文件
  python file_sync.py
  
  # 同步指定群组
  python file_sync.py --group-id 15555548452182
  
  # 干跑测试（只预览，不实际传输）
  python file_sync.py --dry-run
  
  # 同步指定目录
  python file_sync.py --group-id 15555548452182 --directory downloads
        """
    )
    
    parser.add_argument("--config", default="sync_config.json",
                        help="配置文件路径")
    parser.add_argument("--group-id", help="指定要同步的群组ID")
    parser.add_argument("--directory", choices=["downloads", "images"],
                        help="指定要同步的目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="干跑模式（只预览，不实际传输）")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="详细输出")
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 加载配置
    config = DEFAULT_CONFIG.copy()
    config_path = Path(args.config)
    
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
            config.update(user_config)
            logger.info(f"加载配置文件: {args.config}")
    else:
        logger.warning(f"配置文件不存在: {args.config}, 使用默认配置")
    
    # 检查文件同步是否启用
    if not config.get("file_sync", {}).get("enabled", True):
        logger.warning("文件同步未启用")
        return
    
    # 创建同步管理器
    sync_manager = FileSyncManager(config)
    
    try:
        if args.group_id:
            if args.directory:
                # 同步指定群组的指定目录
                sync_manager.sync_directory(args.group_id, args.directory, args.dry_run)
            else:
                # 同步指定群组的所有目录
                sync_manager.sync_group(args.group_id, args.dry_run)
        else:
            # 同步所有群组
            sync_manager.sync_all_groups(args.dry_run)
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️  用户中断同步")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ 同步失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
