#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
爬取后文档处理模块
从 wecom_webhook.py 改写，集成到当前项目架构

四分支处理逻辑：
A. inline_article_url -> 爬取HTML -> 存article_content -> PDF -> 水印 -> 加密 -> 注册topic_files+local_path
B. 附件下载 -> PDF水印加密 -> 更新topic_files.local_path
C. 图片缓存
D. 可选企微推送（由config.toml配置）
"""

import os
import re
import json
import shutil
import hashlib
import random
import time
import textwrap
import traceback
from typing import Dict, List, Optional, Tuple, Any
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from xhtml2pdf import pisa
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

from .logger_config import log_info, log_warning, log_error
from .db_path_manager import get_db_path_manager


class HTMLTagRemover(HTMLParser):
    """HTML标签清理器"""
    def __init__(self):
        super().__init__()
        self.result = []

    def handle_data(self, data):
        self.result.append(data)

    def get_text(self):
        return ''.join(self.result)

    @staticmethod
    def clean_html_tags(text: str) -> str:
        """清理HTML标签，返回纯文本"""
        if not text:
            return ""

        try:
            parser = HTMLTagRemover()
            parser.feed(text)
            text = parser.get_text()
        except Exception:
            pass

        text = re.sub(r'<[^>]+>', '', text)

        html_entities = {
            '&nbsp;': ' ',
            '&lt;': '<',
            '&gt;': '>',
            '&amp;': '&',
            '&quot;': '"',
            '&apos;': "'"
        }
        for entity, char in html_entities.items():
            text = text.replace(entity, char)

        try:
            from urllib.parse import unquote
            text = unquote(text)
        except Exception:
            pass

        text = re.sub(r' +', ' ', text)
        text = text.strip()
        return text


class ZsxqAfterCrawl:
    """爬取后文档处理模块"""

    def __init__(self, crawler, config: dict = None):
        """
        初始化

        Args:
            crawler: ZSXQInteractiveCrawler 实例（提供 cookie, group_id, db, log 等）
            config: 来自 load_config() 的配置字典
        """
        self.crawler = crawler
        self.config = config or {}
        self.session = requests.Session()

        # 频率限制
        webhook_config = self.config.get('wecom_webhook', {})
        self.rate_limit_min = webhook_config.get('rate_limit_min', 30)
        self.rate_limit_max = webhook_config.get('rate_limit_max', 60)

    def log(self, message: str):
        """统一的日志输出"""
        self.crawler.log(message)

    def process_topics(self, topics: List[Dict], stats: Dict = None) -> bool:
        """
        主入口 — ABCD 四分支处理

        Args:
            topics: 话题列表（仅新增话题）
            stats: 存储统计信息

        Returns:
            是否有成功处理的话题
        """
        if not topics:
            return False

        group_id = self.crawler.group_id
        success_count = 0

        for i, topic in enumerate(topics, 1):
            try:
                # 检查停止标志
                if self.crawler.is_stopped():
                    self.log("🛑 after_crawl 处理已停止")
                    break

                talk = topic.get('talk', {})
                # article类型话题没有talk字段，用topic本身作为talk
                if not talk and 'article' in topic:
                    talk = topic
                content = talk.get('text', '')

                # 提取元素
                article_url = self._extract_article_url(talk, topic)
                topic_id = topic.get('topic_id')
                topic_files = talk.get('files', [])

                # ========== 分支A: inline_article_url ==========
                if article_url and 'zsxq' in article_url:
                    # 检查是否已处理过（article_content表已有记录，或已注册PDF）
                    if self._is_article_already_processed(topic_id):
                        self.log(f"📄 第{i}/{len(topics)}条：文章已处理过，跳过 (topic_id={topic_id})")
                    else:
                        self._rate_limit_wait("文章爬取")
                        self.log(f"📄 第{i}/{len(topics)}条：检测到文章链接 {article_url}")

                        if self.handle_article_content(article_url, topic):
                            success_count += 1

                    # 如果同时有附件，继续处理
                    if topic_files:
                        self._rate_limit_wait("附件下载")
                        self.log(f"   📎 继续处理附件...")
                        self.handle_attachments(topic_files, topic)

                    # 如果同时有图片，继续缓存
                    self.handle_images(talk, group_id)
                    continue

                # ========== 分支B: 有附件 ==========
                if topic_files:
                    self._rate_limit_wait("附件下载")
                    self.log(f"📎 第{i}/{len(topics)}条：检测到附件（共{len(topic_files)}个）")

                    if self.handle_attachments(topic_files, topic):
                        success_count += 1

                    # 如果同时有图片，继续缓存
                    self.handle_images(talk, group_id)
                    continue

                # ========== 分支C: 有图片 ==========
                cached, total = self.handle_images(talk, group_id)
                if cached > 0:
                    self.log(f"📷 第{i}/{len(topics)}条：检测到{total}张图片")
                    success_count += 1
                    continue

                # ========== 分支D: 纯文字内容（可选推送）==========
                if content:
                    self.log(f"📝 第{i}/{len(topics)}条：检测到纯文字内容")
                    if self.handle_text_content(content, group_id):
                        success_count += 1

            except Exception as e:
                self.log(f"❌ 第{i}条处理异常: {e}")
                traceback.print_exc()

        self.log(f"📊 爬取后处理总结：{success_count}/{len(topics)}条成功")
        return success_count > 0

    # ============================================================
    # 分支A：处理文章链接
    # ============================================================

    def handle_article_content(self, article_url: str, topic: Dict) -> bool:
        """
        处理文章链接：爬取HTML -> 存article_content -> PDF -> 水印 -> 加密 -> 注册topic_files

        只做一次HTTP请求，复用HTML内容分别用于存文本和转PDF

        Args:
            article_url: inline_article_url
            topic: 话题数据

        Returns:
            是否处理成功
        """
        try:
            talk = topic.get('talk', {})
            if not talk and 'article' in topic:
                talk = topic
            article_info = talk.get('article', {}) if talk else {}
            topic_id = topic.get('topic_id')
            title = topic.get('title') or article_info.get('title', '无标题')

            self.log(f"📄 开始处理文章链接...")

            # 检查是否已有PDF（跳过重复处理）
            topic_files = talk.get('files', [])
            if topic_files:
                for file_info in topic_files:
                    local_path = file_info.get('local_path', '')
                    if local_path and local_path.endswith('.pdf') and os.path.exists(local_path):
                        self.log(f"   ✅ 已存在PDF: {os.path.basename(local_path)}")
                        return True

            # 获取PDF输出目录
            pdf_output_dir = self._get_pdf_output_dir()

            # 一次性完成：爬取HTML -> 存article_content -> 转PDF
            pdf_path = self.convert_url_to_pdf(article_url, pdf_output_dir, title, cookie=self.crawler.cookie)

            if pdf_path:
                # 从已生成的PDF对应的HTML中提取纯文本（避免二次请求）
                # convert_url_to_pdf 内部已获取HTML，这里用 article_content 表做补充
                # 使用 convert_url_to_pdf 缓存的 HTML
                html_content = getattr(self, '_last_fetched_html', None)
                if html_content:
                    text_content = self._extract_text_from_html(html_content)
                    self.crawler.db._upsert_article_content(
                        topic_id=topic_id,
                        article_id=article_info.get('article_id', ''),
                        title=title,
                        text_content=text_content,
                        content_url=article_url
                    )
                    self.log(f"   ✅ 文章纯文本已存入 article_content 表")

                # 水印
                temp_pdf = pdf_path.replace('.pdf', '_temp.pdf')
                if self._add_background_and_noise_to_pdf(pdf_path, temp_pdf, group_id=self.crawler.group_id):
                    # 加密
                    self._encrypt_pdf(temp_pdf)
                    # 覆盖原文件
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                    shutil.move(temp_pdf, pdf_path)
                else:
                    # 水印失败仍加密
                    self._encrypt_pdf(pdf_path)

                # 注册到 topic_files + 更新 local_path
                pdf_name = os.path.basename(pdf_path)
                pdf_size = os.path.getsize(pdf_path)
                self.crawler.db.insert_pdf_file(topic_id, pdf_name, pdf_path, pdf_size)
                self.log(f"   ✅ PDF已注册到 topic_files: {pdf_name}")
                return True

            self.log(f"   ❌ PDF生成失败")
            return False

        except Exception as e:
            self.log(f"   ❌ 文章处理失败: {e}")
            traceback.print_exc()
            return False

    # ============================================================
    # 分支B：处理附件
    # ============================================================

    def handle_attachments(self, topic_files: List[Dict], topic: Dict) -> bool:
        """
        处理附件：下载 -> PDF水印加密 -> 更新topic_files.local_path

        Args:
            topic_files: 附件列表
            topic: 话题数据

        Returns:
            是否处理成功
        """
        try:
            topic_id = topic.get('topic_id')
            self.log(f"📎 开始处理附件（共{len(topic_files)}个）")

            downloader = self.crawler.get_file_downloader()
            processed_count = 0

            for idx, file_info in enumerate(topic_files, 1):
                try:
                    file_name = file_info.get('name', 'Unknown')
                    file_id = file_info.get('file_id')
                    safe_filename = "".join(
                        c for c in file_name
                        if c.isalnum() or c in '._-（）()[]{}' or '\u4e00' <= c <= '\u9fff'
                    )
                    if not safe_filename:
                        safe_filename = f"file_{file_id or 'unknown'}"

                    # 源文件路径
                    source_path = os.path.join(downloader.download_dir, safe_filename)

                    # 下载文件（如果不存在）
                    if not os.path.exists(source_path):
                        file_data = {'file': file_info}
                        result = downloader.download_file(file_data)
                        if not result:
                            self.log(f"   ❌ 文件下载失败: {file_name}")
                            continue

                    # 确认文件存在
                    if not os.path.exists(source_path):
                        self.log(f"   ❌ 文件不存在: {source_path}")
                        continue

                    local_path = os.path.abspath(source_path)

                    # 处理PDF文件：水印 + 加密
                    if source_path.lower().endswith('.pdf'):
                        self.log(f"   🖼️ 处理PDF: {safe_filename}")

                        temp_processed = source_path.replace('.pdf', '_temp.pdf')

                        # 水印
                        if not self._add_background_and_noise_to_pdf(
                                source_path, temp_processed, group_id=self.crawler.group_id):
                            self.log(f"   ⚠️ 水印添加失败，使用源文件")
                            temp_processed = source_path

                        # 加密
                        self._encrypt_pdf(temp_processed)

                        # 用处理后的文件覆盖源文件
                        if os.path.exists(source_path) and temp_processed != source_path:
                            os.remove(source_path)
                            shutil.move(temp_processed, source_path)

                        self.log(f"   ✅ PDF处理完成: {safe_filename}")

                    # 更新 topic_files.local_path
                    if file_id:
                        self.crawler.db.update_topic_file_local_path(topic_id, file_id, local_path)
                        self.log(f"   ✅ 已更新 local_path: {safe_filename}")

                    processed_count += 1

                    # 附件间隔
                    if idx < len(topic_files):
                        self._rate_limit_wait("附件下载")

                except Exception as e:
                    self.log(f"   ❌ 附件处理异常: {e}")
                    traceback.print_exc()

            self.log(f"   ✅ 附件处理完成：{processed_count}/{len(topic_files)}个")
            return processed_count > 0

        except Exception as e:
            self.log(f"   ❌ 附件处理失败: {e}")
            traceback.print_exc()
            return False

    # ============================================================
    # 分支C：处理图片
    # ============================================================

    def handle_images(self, talk: Dict, group_id: str = None) -> Tuple[int, int]:
        """
        处理图片：缓存缩略图和高清图

        Args:
            talk: talk 数据
            group_id: 群组ID

        Returns:
            (缓存成功数, 总图片数)
        """
        from .image_cache_manager import get_image_cache_manager

        # 提取图片URL
        images = []

        # 方法1: 从talk.images字段提取
        if 'images' in talk:
            for img in talk.get('images', []):
                if isinstance(img, dict):
                    img_url = (img.get('original', {}).get('url') or
                               img.get('large', {}).get('url') or
                               img.get('thumbnail', {}).get('url'))
                    if img_url:
                        images.append(img_url)
                elif isinstance(img, str):
                    images.append(img)

        # 方法2: 从talk.article.images字段提取
        if 'article' in talk:
            article = talk.get('article', {})
            if 'images' in article:
                for img in article.get('images', []):
                    if isinstance(img, dict):
                        img_url = (img.get('original', {}).get('url') or
                                   img.get('large', {}).get('url') or
                                   img.get('thumbnail', {}).get('url'))
                        if img_url:
                            images.append(img_url)

        # 方法3: 从HTML内容中提取
        if 'article' in talk:
            article = talk.get('article', {})
            article_content = article.get('article_content', '') or article.get('content', '')
            if article_content:
                img_pattern = r'https?://[^\s<>"]+?(?:\.jpg|\.jpeg|\.png|\.gif|\.webp)'
                found_urls = re.findall(img_pattern, article_content, re.IGNORECASE)
                images.extend(found_urls)

        # 去重
        images = list(dict.fromkeys(images))

        if not images:
            return (0, 0)

        self.log(f"📷 开始处理图片（共{len(images)}张）")

        cache_manager = get_image_cache_manager(group_id)
        cached_count = 0

        for idx, img_url in enumerate(images, 1):
            self.log(f"   📷 处理图片 {idx}/{len(images)}")

            success, path, error = cache_manager.download_and_cache(img_url)

            if success:
                cached_count += 1
                if path:
                    file_size = path.stat().st_size
                    self.log(f"   ✅ 原图缓存成功: {path.name} ({file_size/1024:.1f}KB)")

                # 下载缩略图
                thumbnail_url = None
                if '/large/' in img_url:
                    thumbnail_url = img_url.replace('/large/', '/thumbnail/')
                elif '/original/' in img_url:
                    thumbnail_url = img_url.replace('/original/', '/thumbnail/')

                if thumbnail_url and thumbnail_url != img_url:
                    self._rate_limit_wait("缩略图下载")
                    success_thumb, thumb_path, _ = cache_manager.download_and_cache(thumbnail_url)
                    if success_thumb and thumb_path:
                        file_size = thumb_path.stat().st_size
                        self.log(f"   ✅ 缩略图缓存成功: {thumb_path.name} ({file_size/1024:.1f}KB)")
            else:
                self.log(f"   ❌ 图片下载失败: {error}")

            # 图片间隔
            if idx < len(images):
                self._rate_limit_wait("图片缓存")

        self.log(f"   ✅ 图片处理完成：{cached_count}/{len(images)}张")
        return (cached_count, len(images))

    # ============================================================
    # 分支D：处理纯文字（可选推送）
    # ============================================================

    def handle_text_content(self, content: str, group_id: str) -> bool:
        """
        处理纯文字内容：可选企业微信推送

        Args:
            content: 文字内容（可能含HTML标签）
            group_id: 群组ID

        Returns:
            是否处理成功
        """
        try:
            # 检查是否启用推送
            webhook_config = self.config.get('wecom_webhook', {})
            webhook_url = webhook_config.get('webhook_url', '')

            if not webhook_url:
                self.log(f"   ℹ️ 未配置企微推送，跳过纯文字推送")
                return True  # 不推送也算成功

            # 检查群组是否启用
            groups_config = webhook_config.get('groups', {})
            group_enabled = groups_config.get(str(group_id), {}).get('enabled', False)

            if not group_enabled:
                self.log(f"   ℹ️ 群组 {group_id} 未启用企微推送，跳过")
                return True

            # 清理HTML标签
            content_clean = HTMLTagRemover.clean_html_tags(content)
            content_preview = content_clean[:30] if len(content_clean) > 30 else content_clean

            # 格式化推送内容
            push_text = f"{content_preview}...\n\n详细内容：请访问：http://149.104.30.138:3080/groups/{group_id}"

            self.log(f"📝 推送文字内容...")

            # 发送推送
            if self._send_webhook_text(webhook_url, push_text):
                self.log(f"   ✅ 文字推送成功")
                return True
            else:
                self.log(f"   ❌ 文字推送失败")
                return False

        except Exception as e:
            self.log(f"   ❌ 文本处理失败: {e}")
            return False

    # ============================================================
    # PDF 处理工具
    # ============================================================

    def convert_url_to_pdf(self, url: str, output_dir: str, title: str = None,
                           cookie: str = None) -> Optional[str]:
        """
        使用xhtml2pdf将网页URL转换为PDF文件

        Args:
            url: 网页URL
            output_dir: PDF输出目录
            title: 可选的文章标题
            cookie: 知识星球Cookie

        Returns:
            PDF文件路径，失败返回None
        """
        try:
            self.log(f"   📄 开始转换网页为PDF: {url}")

            os.makedirs(output_dir, exist_ok=True)

            # 生成PDF文件名
            if title and title.strip():
                safe_title = re.sub(r'[^\w\s\u4e00-\u9fff]', '', title.strip())
                safe_title = re.sub(r'\s+', '', safe_title)
                if len(safe_title) > 100:
                    safe_title = safe_title[:100]
                pdf_filename = f"{safe_title}.pdf"
            else:
                file_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                pdf_filename = f"article_{file_hash}.pdf"

            pdf_path = os.path.join(output_dir, pdf_filename)

            # 如果PDF已存在，直接返回
            if os.path.exists(pdf_path):
                file_size = os.path.getsize(pdf_path)
                self.log(f"   ✅ PDF已存在，跳过转换 ({self._format_file_size(file_size)})")
                return pdf_path

            self.log(f"   📝 文章标题: {title}")
            self.log(f"   📄 PDF文件名: {pdf_filename}")

            # 获取网页HTML
            self.log(f"   🔍 获取网页HTML内容...")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }

            parsed_url = urlparse(url)
            domain = parsed_url.netloc

            if "zsxq.com" in domain:
                self.log(f"   🔗 检测到知识星球域名，使用Cookie")
                if cookie:
                    headers["Cookie"] = cookie
                headers["Referer"] = "https://wx.zsxq.com/"
                headers["Origin"] = "https://wx.zsxq.com"
            else:
                self.log(f"   🔗 外部链接域名: {domain}")

            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            html_content = response.text

            # 缓存原始HTML供 handle_article_content 提取文本使用（避免二次请求）
            self._last_fetched_html = html_content

            self.log(f"   ✅ 获取到HTML内容: {len(html_content)} 字符")

            # 使用 BeautifulSoup 清理HTML，移除重复内容
            html_content = self._clean_html_for_pdf(html_content)
            self.log(f"   ✅ HTML清理完成: {len(html_content)} 字符")

            # 调整图片样式
            def add_responsive_style(match):
                tag = match.group(0)
                if 'style="' in tag:
                    tag = tag.replace('style="', 'style="max-width: 100%; height: auto; ')
                elif "style='" in tag:
                    tag = tag.replace("style='", "style='max-width: 100%; height: auto; ")
                else:
                    if ' src="' in tag:
                        tag = tag.replace(' src="', ' style="max-width: 100%; height: auto;" src="')
                    elif " src='" in tag:
                        tag = tag.replace(" src='", " style='max-width: 100%; height: auto;' src='")
                    else:
                        tag = tag.replace('>', ' style="max-width: 100%; height: auto;">')
                return tag

            html_content = re.sub(r'<img[^>]+>', add_responsive_style, html_content, flags=re.IGNORECASE)

            self.log(f"   🔍 开始使用xhtml2pdf转换PDF...")

            html_content = re.sub(r'<\?xml[^>]*\?>\s*', '', html_content)
            html_content = re.sub(r'<!DOCTYPE[^>]*>\s*', '', html_content)
            html_content = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n' + html_content

            # 文本换行处理
            html_content = self._html_wrap_content(html_content, width=46)

            # 清理HTML结构：移除空段落、合并连续段落、保留1行空行
            html_content = re.sub(r'<p>\s*</p>', '', html_content)
            html_content = re.sub(r'<p([^>]*)>\s*(<img[^>]+>)\s*</p>', r'\2', html_content, flags=re.IGNORECASE)
            # 将 <p><br/></p> 空段落转为单个换行标记
            html_content = re.sub(r'<p>\s*<br\s*/?>\s*</p>', '<br/><br/>', html_content)
            # 规范化 <br/> 标签
            html_content = re.sub(r'<br\s*/?>\s*', '<br/>', html_content)
            # 合并连续段落为单个换行
            html_content = re.sub(r'</p>\s*<p>', '<br/>', html_content)
            # 连续3个及以上换行合并为2个（保留1行空行）
            html_content = re.sub(r'(<br\s*/?>\s*){3,}', '<br/><br/>', html_content)

            # 注入CSS样式
            css = '''
                <style>
                    @page { size: A4; margin: 1.2cm 1.5cm; }
                    body {
                        font-family: STSong-Light, SimSun, Times New Roman, Arial, sans-serif;
                        line-height: 1.4;
                        margin: 0;
                        padding: 5px;
                        font-size: 11pt;
                        word-wrap: break-word;
                        word-break: break-word;
                    }
                    img { max-width: 100% !important; height: auto !important; display: block; margin: 4px 0; }
                    p, div { margin: 0; padding: 0; word-wrap: break-word; overflow-wrap: break-word; }
                    pre, code { white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word; }
                    table { max-width: 100%; word-wrap: break-word; }
                    h1, h2, h3, h4, h5, h6 { margin: 0.5em 0 0.3em 0; font-weight: bold; word-wrap: break-word; }
                </style>
            '''

            if '<head>' in html_content:
                html_content = html_content.replace('<head>', f'<head>{css}')
            elif '<html>' in html_content:
                html_content = html_content.replace('<html>', f'<html><head>{css}</head>')
            else:
                html_content = f'<html><head>{css}</head><body>{html_content}</body></html>'

            # 转换PDF
            with open(pdf_path, 'wb') as pdf_file:
                pisa_status = pisa.CreatePDF(
                    src=BytesIO(html_content.encode('utf-8')),
                    dest=pdf_file,
                    encoding='utf-8'
                )

            if pisa_status.err:
                self.log(f"   ⚠️ PDF转换报告异常: {pisa_status.err}")
            else:
                self.log(f"   ✅ xhtml2pdf转换完成")

            # 检查PDF文件
            if os.path.exists(pdf_path):
                file_size = os.path.getsize(pdf_path)
                self.log(f"   📊 PDF文件大小: {self._format_file_size(file_size)}")

                if file_size > 10 * 1024:
                    self.log(f"   ✅ PDF转换成功: {pdf_path}")
                    return pdf_path
                else:
                    self.log(f"   ⚠️ PDF文件过小")
                    return pdf_path
            else:
                self.log(f"   ❌ PDF文件未生成")
                return None

        except Exception as e:
            self.log(f"   ❌ PDF转换异常: {e}")
            traceback.print_exc()
            return None

    def _add_background_and_noise_to_pdf(self, source_pdf: str, output_pdf: str,
                                          group_id: str = None) -> bool:
        """为 PDF 添加背景图和干扰功能"""
        try:
            bg_path = os.path.join(os.path.dirname(__file__), "images", "pdf_background.png")
            temp_dir = os.path.join(os.path.dirname(__file__), "temp_pdf_pages")
            os.makedirs(temp_dir, exist_ok=True)

            src_doc = fitz.open(source_pdf)
            out_doc = fitz.open()

            # 加载背景图
            bg_image = None
            if os.path.exists(bg_path):
                bg_image = Image.open(bg_path)
                if bg_image.mode != 'RGB':
                    bg_image = bg_image.convert('RGB')
                self.log(f"   📐 背景图尺寸: {bg_image.size[0]} x {bg_image.size[1]}")

            # 干扰文字配置
            noise_text = "（请访问网页：https://xq.openshare.eu.cc/）"
            font_path = r"C:\Windows\Fonts\msyh.ttc"
            if not os.path.exists(font_path):
                font_path = None
            font_size = 10
            font_color = (0, 0, 0)
            insert_times = 3

            for page_num in range(len(src_doc)):
                src_page = src_doc[page_num]
                src_w = src_page.rect.width
                src_h = src_page.rect.height

                out_page = out_doc.new_page(width=src_w, height=src_h)

                # 插入背景图
                if bg_image:
                    temp_bg_path = os.path.join(temp_dir, f"bg_{page_num}.png")
                    resized_bg = bg_image.resize((int(src_w), int(src_h)), Image.Resampling.LANCZOS)
                    resized_bg.save(temp_bg_path)
                    out_page.insert_image(fitz.Rect(0, 0, src_w, src_h), filename=temp_bg_path)
                    try:
                        os.remove(temp_bg_path)
                    except Exception:
                        pass

                # 插入源PDF内容
                out_page.show_pdf_page(
                    fitz.Rect(0, 0, src_w, src_h),
                    src_doc,
                    page_num
                )

                # 添加干扰文字
                if font_path and os.path.exists(font_path):
                    for _ in range(insert_times):
                        noise_x = random.randint(30, max(31, int(src_w) - 150))
                        noise_y = random.randint(50, max(51, int(src_h) - 50))

                        out_page.insert_text(
                            fitz.Point(noise_x, noise_y),
                            noise_text,
                            fontname="china-s",
                            fontfile=font_path,
                            fontsize=font_size,
                            color=font_color
                        )

                self.log(f"   📄 第{page_num+1}页: {src_w:.0f}x{src_h:.0f}, 已添加干扰文字")

            out_doc.save(output_pdf)
            out_doc.close()
            src_doc.close()

            self.log(f"   ✅ 背景和干扰添加完成")
            return True

        except Exception as e:
            self.log(f"   ❌ 背景添加失败: {e}")
            traceback.print_exc()
            return False

    def _encrypt_pdf(self, pdf_path: str, owner_password: str = "protect_pdf@Arron") -> bool:
        """
        使用 PyMuPDF 对 PDF 进行加密保护
        用户无需密码即可打开查看，但无法修改、复制、导出
        """
        try:
            doc = fitz.open(pdf_path)

            perm = 0  # 只读，禁止所有操作

            temp_path = pdf_path + ".encrypted"
            doc.save(
                temp_path,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw=owner_password,
                user_pw="",
                permissions=perm
            )
            doc.close()

            os.replace(temp_path, pdf_path)

            self.log(f"   🔒 PDF加密完成（禁止修改/复制/导出）")
            return True

        except Exception as e:
            self.log(f"   ❌ PDF加密失败: {e}")
            traceback.print_exc()
            return False

    # ============================================================
    # 辅助方法
    # ============================================================

    def _is_article_already_processed(self, topic_id: int) -> bool:
        """检查文章是否已经处理过（PDF文件已生成且存在于磁盘）

        设计原则：
        - 只检查最终产物（PDF文件），不检查中间产物（article_content）
        - article_content 有记录但 PDF 不存在 = 处理未完成，应重新执行
        - topic_files 有记录但文件已删除 = 应重新生成
        """
        try:
            # 检查 topic_files 中是否有已注册的 PDF 文件且文件实际存在
            self.crawler.db.cursor.execute('''
                SELECT local_path FROM topic_files
                WHERE topic_id = ? AND name LIKE '%.pdf' AND local_path != ''
            ''', (topic_id,))
            rows = self.crawler.db.cursor.fetchall()
            for row in rows:
                local_path = row[0]
                if local_path and os.path.exists(local_path):
                    return True

            # 也检查 PDF 输出目录中是否有对应文件（可能未注册到 topic_files）
            # 通过 articles 表获取标题来推算文件名
            self.crawler.db.cursor.execute('''
                SELECT a.title, a.inline_article_url, a.article_url
                FROM articles a
                WHERE a.topic_id = ?
            ''', (topic_id,))
            article_row = self.crawler.db.cursor.fetchone()
            if article_row:
                pdf_output_dir = self._get_pdf_output_dir()
                title = article_row[0]
                article_url = article_row[1] or article_row[2] or ''

                # 推算 PDF 文件名（与 convert_url_to_pdf 逻辑一致）
                if title and title.strip():
                    safe_title = re.sub(r'[^\w\s\u4e00-\u9fff]', '', title.strip())
                    safe_title = re.sub(r'\s+', '', safe_title)
                    if len(safe_title) > 100:
                        safe_title = safe_title[:100]
                    pdf_filename = f"{safe_title}.pdf"
                else:
                    file_hash = hashlib.md5(article_url.encode()).hexdigest()[:12]
                    pdf_filename = f"article_{file_hash}.pdf"

                pdf_path = os.path.join(pdf_output_dir, pdf_filename)
                if os.path.exists(pdf_path):
                    return True

            return False

        except Exception:
            return False

    def _extract_article_url(self, talk: Dict, topic: Dict) -> Optional[str]:
        """提取文章链接"""
        # 1. talk.article.inline_article_url (talk类型话题中的文章)
        if talk and 'article' in talk:
            article_data = talk.get('article', {})
            article_url = article_data.get('inline_article_url') or article_data.get('article_url')
            if article_url:
                return article_url

        # 2. topic.article.inline_article_url (article类型话题)
        if 'article' in topic:
            article_data = topic.get('article', {})
            article_url = article_data.get('inline_article_url') or article_data.get('article_url')
            if article_url:
                return article_url

        # 3. 顶层字段
        return topic.get('inline_article_url') or topic.get('article_url')

    def _fetch_article_html(self, article_url: str) -> Optional[str]:
        """爬取文章HTML内容"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }

            parsed_url = urlparse(article_url)
            if "zsxq.com" in parsed_url.netloc:
                headers["Cookie"] = self.crawler.cookie
                headers["Referer"] = "https://wx.zsxq.com/"
                headers["Origin"] = "https://wx.zsxq.com"

            response = requests.get(article_url, headers=headers, timeout=60)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            return response.text

        except Exception as e:
            self.log(f"   ❌ 爬取文章HTML失败: {e}")
            return None

    def _extract_text_from_html(self, html_content: str) -> str:
        """使用BeautifulSoup从HTML中提取纯文本"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # 移除script和style标签
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator='\n', strip=True)
            return text
        except Exception as e:
            self.log(f"   ⚠️ BeautifulSoup提取文本失败，使用正则: {e}")
            return HTMLTagRemover.clean_html_tags(html_content)

    def _get_pdf_output_dir(self) -> str:
        """获取PDF输出目录"""
        download_config = self.config.get('download', {})
        download_dir = download_config.get('dir', 'downloads')

        if download_dir == "downloads":
            path_manager = get_db_path_manager()
            group_dir = path_manager.get_group_dir(self.crawler.group_id)
            pdf_dir = os.path.join(group_dir, 'downloads')
        else:
            pdf_dir = os.path.join(download_dir, f"group_{self.crawler.group_id}")

        os.makedirs(pdf_dir, exist_ok=True)
        return pdf_dir

    def _clean_html_for_pdf(self, html_content: str) -> str:
        """使用BeautifulSoup清理HTML，移除编辑器重复内容

        zsxq文章页面的实际HTML结构（经debug.html验证）：

        <div class="content-container quill-editor">
          <div class="title">标题</div>
          <div class="ql-snow">
            <div class="content ql-editor">正文内容 ← 保留这个</div>
          </div>
          <div class="tiptap-preview">正文内容的副本 ← 重复！需移除</div>
          <div class="milkdown-preview">正文内容的副本 ← 重复！需移除</div>
          <input .../> 隐藏字段
        </div>

        清理策略：保留 .ql-editor 正文，移除所有已知的编辑器预览/副本元素
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # 1. 移除 <script> 和 <noscript> 标签
            for tag in soup.find_all(['script', 'noscript']):
                tag.decompose()

            # 2. 移除所有已知的编辑器预览/副本元素（与正文内容重复）
            #    - tiptap-preview：tiptap编辑器预览区（实测遇到的重复源）
            #    - milkdown / milkdown-preview：milkdown编辑器预览区
            #    - ProseMirror：ProseMirror编辑器区域
            editor_preview_patterns = [
                r'tiptap',           # tiptap-preview
                r'milkdown',         # milkdown-preview
                r'ProseMirror',      # ProseMirror 编辑区
                r'prosemirror',      # prosemirror 编辑区
            ]
            for pattern in editor_preview_patterns:
                for tag in soup.find_all(class_=re.compile(pattern, re.IGNORECASE)):
                    self.log(f"   🧹 移除编辑器预览元素: <{tag.name} class='{' '.join(tag.get('class', []))}'>")
                    tag.decompose()

            # 3. 移除所有 contenteditable 元素（可编辑区域，通常是编辑器的副本）
            for tag in soup.find_all(attrs={'contenteditable': True}):
                self.log(f"   🧹 移除contenteditable元素: <{tag.name} class='{' '.join(tag.get('class', []))}'>")
                tag.decompose()

            # 4. 移除隐藏元素（display:none / visibility:hidden）
            for tag in soup.find_all(style=re.compile(r'display\s*:\s*none|visibility\s*:\s*hidden', re.IGNORECASE)):
                tag.decompose()

            # 5. 移除编辑器工具栏等辅助元素
            for selector in ['editor-toolbar', 'editor-menu', 'milkdown-menu', 'toolbar']:
                for tag in soup.find_all(class_=selector):
                    tag.decompose()

            # 6. 移除隐藏的input字段
            for tag in soup.find_all('input', {'type': 'hidden'}):
                tag.decompose()

            result = str(soup)

            # 7. 后备正则清理：处理BeautifulSoup可能遗漏的编辑器标签残留
            for pattern in ['tiptap', 'milkdown', 'prosemirror']:
                for _ in range(3):  # 最多3层嵌套
                    old_len = len(result)
                    result = re.sub(
                        rf'<div[^>]*{pattern}[^>]*>(?:(?!</?div).)*</div>',
                        '', result, flags=re.DOTALL | re.IGNORECASE
                    )
                    if len(result) == old_len:
                        break

            return result

        except Exception as e:
            self.log(f"   ⚠️ BeautifulSoup清理HTML失败，使用原始HTML: {e}")
            traceback.print_exc()
            return html_content

    def _html_wrap_content(self, html_content: str, width: int = 46) -> str:
        """对HTML中的文本内容进行换行处理，避免PDF生成时文本溢出"""
        try:
            parts = re.split(r'(<[^>]+>)', html_content)
            result = []

            for part in parts:
                if part.startswith('<') and part.endswith('>'):
                    if part.startswith('<a ') or part.startswith('</a>'):
                        result.append('<br>' + part + '<br>')
                    else:
                        result.append(part)
                else:
                    if part.strip():
                        part = re.sub(r'(https?://[^\s<>"\'\)]+)', r'<br>\1<br>', part)
                        wrapped = textwrap.fill(part, width=width)
                        result.append(wrapped.replace('\n', '<br>'))
                    else:
                        result.append(part)

            html_result = ''.join(result)
            html_result = re.sub(r'(<br>\s*){2,}', '<br>', html_result)
            return html_result
        except Exception as e:
            self.log(f"   ⚠️ 文本换行处理失败: {e}")
            return html_content

    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def _rate_limit_wait(self, operation_name: str = "操作"):
        """频率限制：随机等待"""
        wait_time = random.randint(self.rate_limit_min, self.rate_limit_max)
        self.log(f"⏳ {operation_name}频率限制，等待 {wait_time:.0f} 秒...")
        time.sleep(wait_time)

    def _send_webhook_text(self, webhook_url: str, content: str) -> bool:
        """发送企业微信文本消息"""
        try:
            data = {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }

            response = self.session.post(
                webhook_url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            result = response.json()
            if result.get("errcode") == 0:
                return True
            else:
                self.log(f"   ❌ 企微消息发送失败: {result.get('errmsg')}")
                return False

        except Exception as e:
            self.log(f"   ❌ 企微消息发送异常: {e}")
            return False
