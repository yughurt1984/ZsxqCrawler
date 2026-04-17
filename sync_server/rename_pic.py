#!/usr/bin/env python3
"""
重命名downloads目录中的图片文件
从 {8位MD5}_{序号}.{扩展名} 改为 {完整32位MD5}.{扩展名}
"""

import os
import re
import hashlib
import sqlite3
from pathlib import Path
from typing import Optional, Tuple
import shutil
from db_path_manager import get_db_path_manager


def get_db_path(group_id: str) -> Path:
    """获取数据库路径"""
    path_manager = get_db_path_manager()
    return path_manager.get_topics_db_path(group_id)


def calculate_md5(url: str) -> str:
    """计算URL的MD5值"""
    return hashlib.md5(url.encode('utf-8')).hexdigest()


def find_image_url_by_partial_md5(db_path: Path, partial_md5: str) -> Optional[Tuple[str, str]]:
    """
    根据部分MD5查找数据库中的图片URL
    
    Args:
        db_path: 数据库路径
        partial_md5: 8位MD5值
        
    Returns:
        (url, url_type) 或 None
        url_type: 'thumbnail', 'large', 'original'
    """
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 查询所有图片URL
        cursor.execute("""
            SELECT image_id, thumbnail_url, large_url, original_url
            FROM images
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        # 遍历所有图片，计算MD5并匹配
        for row in rows:
            image_id, thumbnail_url, large_url, original_url = row
            
            # 检查三种URL
            for url_type, url in [('thumbnail', thumbnail_url), 
                                  ('large', large_url), 
                                  ('original', original_url)]:
                if url:
                    full_md5 = calculate_md5(url)
                    if full_md5.startswith(partial_md5):
                        return (url, url_type)
        
        return None
        
    except Exception as e:
        print(f"❌ 数据库查询失败: {e}")
        return None


def rename_image_file(old_path: Path, new_path: Path, dry_run: bool = False) -> bool:
    """
    重命名图片文件
    
    Args:
        old_path: 旧文件路径
        new_path: 新文件路径
        dry_run: 是否只预览不执行
        
    Returns:
        是否成功
    """
    try:
        # 检查新文件是否已存在
        if new_path.exists():
            print(f"   ⚠️  目标文件已存在，跳过: {new_path.name}")
            return False
        
        if dry_run:
            print(f"   [预览] {old_path.name} -> {new_path.name}")
        else:
            shutil.move(str(old_path), str(new_path))
            print(f"   ✅ {old_path.name} -> {new_path.name}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ 重命名失败: {e}")
        return False


def process_downloads_dir(group_id: str, dry_run: bool = True):
    """
    处理指定群组的downloads目录
    
    Args:
        group_id: 群组ID
        dry_run: 是否只预览不执行
    """
    path_manager = get_db_path_manager()
    
    # 获取目录路径
    group_dir = path_manager.get_group_dir(group_id)
    downloads_dir = group_dir / 'downloads'
    db_path = get_db_path(group_id)
    
    if not downloads_dir.exists():
        print(f"❌ downloads目录不存在: {downloads_dir}")
        return
    
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    print(f"\n{'='*80}")
    print(f"处理群组: {group_id}")
    print(f"downloads目录: {downloads_dir}")
    print(f"数据库: {db_path}")
    print(f"模式: {'预览模式（不实际执行）' if dry_run else '执行模式'}")
    print(f"{'='*80}\n")
    
    # 扫描图片文件
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    image_files = [f for f in downloads_dir.iterdir() 
                   if f.is_file() and f.suffix.lower() in image_extensions]
    
    print(f"📁 找到 {len(image_files)} 个图片文件\n")
    
    # 统计
    success_count = 0
    skip_count = 0
    fail_count = 0
    
    # 处理每个图片
    for i, img_file in enumerate(image_files, 1):
        print(f"[{i}/{len(image_files)}] 处理: {img_file.name}")
        
        # 解析文件名：{8位MD5}_{序号}.{扩展名}
        match = re.match(r'^([a-f0-9]{8})_(\d+)(\.\w+)$', img_file.name)
        if not match:
            print(f"   ⚠️  文件名格式不匹配，跳过")
            skip_count += 1
            continue
        
        partial_md5 = match.group(1)
        index = match.group(2)
        ext = match.group(3)
        
        print(f"   部分MD5: {partial_md5}, 序号: {index}")
        
        # 查询数据库获取完整URL
        result = find_image_url_by_partial_md5(db_path, partial_md5)
        
        if not result:
            print(f"   ❌ 数据库中未找到匹配的URL")
            fail_count += 1
            continue
        
        url, url_type = result
        full_md5 = calculate_md5(url)
        
        print(f"   URL类型: {url_type}")
        print(f"   完整MD5: {full_md5}")
        
        # 新文件名
        new_filename = f"{full_md5}{ext}"
        new_path = downloads_dir / new_filename
        
        # 重命名
        if rename_image_file(img_file, new_path, dry_run):
            success_count += 1
        else:
            fail_count += 1
    
    # 打印统计
    print(f"\n{'='*80}")
    print(f"处理完成:")
    print(f"  ✅ 成功: {success_count}")
    print(f"  ⏭️  跳过: {skip_count}")
    print(f"  ❌ 失败: {fail_count}")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='重命名downloads目录中的图片文件')
    parser.add_argument('group_id', help='群组ID')
    parser.add_argument('--execute', action='store_true', help='实际执行（默认只预览）')
    
    args = parser.parse_args()
    
    process_downloads_dir(args.group_id, dry_run=not args.execute)
