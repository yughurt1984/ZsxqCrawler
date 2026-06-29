#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件增量同步脚本 - 使用 Windows 原生 SSH + scp
功能:
1. 同步 downloads 和 images 目录
2. 增量同步，只传输远程不存在的新文件
3. 支持干跑模式预览

SSH 方案：
  使用 Windows 原生 SSH（与 incremental_sync.py 一致），
  避免 Cygwin SSH 的密钥权限映射问题。
"""

import os
import sys
import json
import argparse
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional
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
        "directories": ["downloads", "images"]
    }
}


def find_windows_ssh() -> Optional[str]:
    """查找 Windows 原生 SSH 路径"""
    # 优先查找 System32 下的 OpenSSH
    system_ssh = Path("C:/Windows/System32/OpenSSH/ssh.exe")
    if system_ssh.exists():
        return str(system_ssh)
    
    # 通过 PATH 查找
    ssh_path = shutil.which("ssh", path=os.environ.get('PATH', ''))
    if ssh_path:
        return ssh_path
    
    return None


class FileSyncManager:
    """文件同步管理器 - 使用增量 scp（Windows 原生 SSH）
    
    与 incremental_sync.py 保持一致的 SSH 方案：
    - 使用 Windows 原生 SSH（不依赖 Cygwin SSH）
    - 密钥路径使用 Windows 格式（如 C:/Users/arron/.ssh/yecaoyun_id_rsa）
    - 无需设置 HOME/CYGWIN 等环境变量
    - 增量同步：先获取远程文件列表，只上传新文件
    """
    
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
        
        # 查找 SSH 路径
        self.ssh_exe = find_windows_ssh()
        if not self.ssh_exe:
            logger.error("未找到 Windows SSH，请确保 OpenSSH 已安装")
        
        # 统计
        self.stats = {
            "directories_synced": 0,
            "total_files": 0,
            "total_size": 0,
            "errors": []
        }
    
    def _build_ssh_args(self) -> list:
        """构建 SSH 公共参数"""
        args = ["-p", str(self.server_port)]
        args.extend(["-o", "StrictHostKeyChecking=no"])
        args.extend(["-o", "UserKnownHostsFile=NUL"])
        args.extend(["-o", "IdentitiesOnly=yes"])
        if self.ssh_key:
            args.extend(["-i", self.ssh_key])
        return args
    
    def _ssh_exec(self, command: str, capture: bool = True) -> subprocess.CompletedProcess:
        """通过 SSH 在服务器上执行命令"""
        cmd = [self.ssh_exe]
        cmd.extend(self._build_ssh_args())
        cmd.extend([f"{self.server_user}@{self.server_host}", command])
        
        if capture:
            return subprocess.run(cmd, capture_output=True, text=True, 
                                  encoding='utf-8', errors='replace', check=False)
        else:
            return subprocess.run(cmd, text=True, encoding='utf-8', errors='replace', check=False)
    
    def _scp_file(self, local_file: str, remote_dir: str) -> subprocess.CompletedProcess:
        """通过 scp 上传单个文件"""
        scp_exe = self.ssh_exe.replace("ssh.exe", "scp.exe").replace("ssh", "scp")
        cmd = [scp_exe, "-P", str(self.server_port)]
        cmd.extend(["-o", "StrictHostKeyChecking=no"])
        cmd.extend(["-o", "UserKnownHostsFile=NUL"])
        cmd.extend(["-o", "IdentitiesOnly=yes"])
        if self.ssh_key:
            cmd.extend(["-i", self.ssh_key])
        cmd.extend([local_file, f"{self.server_user}@{self.server_host}:{remote_dir}"])
        
        return subprocess.run(cmd, capture_output=True, text=True, 
                              encoding='utf-8', errors='replace', check=False)
    
    def _get_remote_file_list(self, remote_dir: str) -> set:
        """通过 SSH 获取服务器上的文件相对路径集合"""
        result = self._ssh_exec(f"find {remote_dir} -type f 2>/dev/null")
        if result.returncode != 0 or not result.stdout:
            logger.warning(f"无法获取远程文件列表: {result.stderr or '无输出'}")
            return set()
        
        remote_rel_files = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith(remote_dir):
                rel = line[len(remote_dir):]
                remote_rel_files.add(rel)
        
        return remote_rel_files
    
    def sync_directory(self, group_id: str, directory: str, dry_run: bool = False) -> bool:
        """增量 scp 同步：只传输本地有但远程没有的文件
        
        步骤：
        1. SSH 获取远程文件列表
        2. 获取本地文件列表
        3. 对比找出新增文件
        4. SSH 创建远程目录结构
        5. scp 逐个上传新增文件
        """
        
        local_path = self.local_base / group_id / directory
        local_path.mkdir(parents=True, exist_ok=True)
        remote_dir = f"{self.server_base}/{group_id}/{directory}/"
        
        logger.info("=" * 60)
        logger.info(f"同步目录: {group_id}/{directory}")
        logger.info("=" * 60)
        
        # 1. 获取远程文件列表（相对路径）
        remote_rel_files = self._get_remote_file_list(remote_dir)
        logger.info(f"远程已有 {len(remote_rel_files)} 个文件")
        
        # 2. 获取本地文件列表（递归，包含子目录）
        local_files = {}
        for f in local_path.rglob("*"):
            if f.is_file():
                rel_path = f.relative_to(local_path)
                # 统一使用 / 作为分隔符（与远程 find 输出一致）
                local_files[str(rel_path).replace("\\", "/")] = f
        
        logger.info(f"本地共 {len(local_files)} 个文件")
        
        # 3. 找出需要上传的文件（远程不存在该相对路径）
        files_to_upload = [f for rel, f in local_files.items() if rel not in remote_rel_files]
        
        logger.info(f"需要上传 {len(files_to_upload)} 个新文件")
        
        if dry_run:
            if files_to_upload:
                for f in files_to_upload:
                    logger.info(f"  [干跑] 将上传: {f.relative_to(local_path)}")
            else:
                logger.info("  [干跑] 无新增文件需要上传")
            return True
        
        if not files_to_upload:
            logger.info("无新增文件，跳过上传")
            logger.info(f"✅ 同步完成: {group_id}/{directory}")
            self.stats["directories_synced"] += 1
            return True
        
        # 4. SSH 创建远程目录结构（包含子目录）
        subdirs = set()
        for rel in local_files:
            if "/" in rel:
                subdir = rel.rsplit("/", 1)[0]
                subdirs.add(subdir)
        
        # 需要创建的远程目录
        dirs_to_create = [remote_dir]
        for subdir in subdirs:
            dirs_to_create.append(f"{remote_dir}{subdir}/")
        
        mkdir_cmd = "mkdir -p " + " ".join(f"'{d}'" for d in dirs_to_create)
        result = self._ssh_exec(mkdir_cmd)
        if result.returncode != 0:
            logger.error(f"创建远程目录失败: {result.stderr}")
            self.stats["errors"].append(f"{group_id}/{directory}: 创建目录失败")
            return False
        
        # 5. 逐个上传新文件
        uploaded = 0
        for f in files_to_upload:
            rel_str = str(f.relative_to(local_path)).replace("\\", "/")
            
            # 确定远程目标路径
            if "/" in rel_str:
                target_dir = f"{remote_dir}{rel_str.rsplit('/', 1)[0]}/"
            else:
                target_dir = remote_dir
            
            logger.info(f"上传: {rel_str}")
            result = self._scp_file(str(f), target_dir)
            
            if result.returncode != 0:
                logger.warning(f"上传失败: {rel_str} - {result.stderr}")
            else:
                uploaded += 1
        
        logger.info(f"成功上传 {uploaded}/{len(files_to_upload)} 个文件")
        self.stats["total_files"] += uploaded
        
        if uploaded == len(files_to_upload):
            logger.info(f"✅ 同步完成: {group_id}/{directory}")
            self.stats["directories_synced"] += 1
            return True
        else:
            self.stats["errors"].append(f"{group_id}/{directory}: {len(files_to_upload)-uploaded} 个文件上传失败")
            return False
    
    def sync_group(self, group_id: str, dry_run: bool = False):
        """同步单个群组的文件目录"""
        
        logger.info("=" * 60)
        logger.info(f"开始同步群组: {group_id}")
        logger.info("=" * 60)
        
        for directory in self.sync_dirs:
            self.sync_directory(group_id, directory, dry_run)
    
    def sync_all_groups(self, dry_run: bool = False):
        """同步所有群组的文件目录"""
        
        logger.info("=" * 60)
        logger.info("开始文件同步 - 所有群组")
        logger.info("=" * 60)
        
        if not self.local_base.exists():
            logger.warning(f"本地数据库目录不存在: {self.local_base}")
            return
        
        for group_dir in self.local_base.iterdir():
            if group_dir.is_dir() and group_dir.name.isdigit():
                self.sync_group(group_dir.name, dry_run)
        
        self.print_summary()
    
    def print_summary(self):
        """打印同步摘要"""
        logger.info("=" * 60)
        logger.info("同步摘要")
        logger.info("=" * 60)
        logger.info(f"目录同步: {self.stats['directories_synced']} 个")
        logger.info(f"文件上传: {self.stats['total_files']} 个")
        
        if self.stats["errors"]:
            logger.error(f"错误数量: {len(self.stats['errors'])}")
            for error in self.stats["errors"]:
                logger.error(f"  - {error}")


def main():
    parser = argparse.ArgumentParser(
        description="文件增量同步 - 使用 Windows SSH + scp",
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
    
    if not config.get("file_sync", {}).get("enabled", True):
        logger.warning("文件同步未启用")
        return
    
    sync_manager = FileSyncManager(config)
    
    try:
        if args.group_id:
            if args.directory:
                sync_manager.sync_directory(args.group_id, args.directory, args.dry_run)
            else:
                sync_manager.sync_group(args.group_id, args.dry_run)
        else:
            sync_manager.sync_all_groups(args.dry_run)
        
    except KeyboardInterrupt:
        logger.warning("用户中断同步")
        sys.exit(0)
    except Exception as e:
        logger.error(f"同步失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
