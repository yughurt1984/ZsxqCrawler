"""
企业微信Webhook推送模块
用于在爬取到新内容后推送通知
"""
import requests
import json
import os
import re
from typing import Dict, List, Optional, Tuple
from html.parser import HTMLParser
from db_path_manager import get_db_path_manager
from zsxq_interactive_crawler import load_config

from image_cache_manager import get_image_cache_manager #处理图片
from xhtml2pdf import pisa
from io import BytesIO
from urllib.parse import urlparse
import textwrap  # ✅ 添加文本换行支持
import fitz  # PyMuPDF
import traceback
import hashlib
import random
import time
from datetime import datetime
import shutil
from PIL import Image, ImageDraw, ImageFont


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
        """
        清理HTML标签，返回纯文本
        
        Args:
            text: 包含HTML标签的文本
            
        Returns:
            清理后的纯文本
        """
        if not text:
            return ""
        
        # 方法1: 使用HTMLParser清理
        try:
            parser = HTMLTagRemover()
            parser.feed(text)
            text = parser.get_text()
        except:
            # 如果HTMLParser失败，使用正则表达式
            pass
        
        # 方法2: 使用正则表达式清理剩余的HTML标签
        # 匹配所有HTML标签: <tag> 或 <tag />
        text = re.sub(r'<[^>]+>', '', text)
        
        # 清理HTML实体（如 &nbsp; 等）
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
        
        # 清理URL编码的字符（如 %EF%BC%8C）
        try:
            # 解析URL编码
            from urllib.parse import unquote
            text = unquote(text)
        except:
            pass
        
        # 清理多余的空白字符
        text = re.sub(r' +', ' ', text)
        text = text.strip()
        
        return text


class WeComWebhook:
    """企业微信机器人Webhook推送类"""
        
    def __init__(self, webhook_url: str, enabled: bool = True, log_callback=None, config: dict = None):
        """
        初始化企业微信Webhook
        """
        self.webhook_url = webhook_url
        self.enabled = enabled
        self.session = requests.Session()
        self.log_callback = log_callback
        self.config = config or {}
        
        # 频率限制相关 - 随机范围
        webhook_config = self.config.get('wecom_webhook', {})
        self.rate_limit_min = webhook_config.get('rate_limit_min', 30)
        self.rate_limit_max = webhook_config.get('rate_limit_max', 60)
        self.last_operation_time = 0
        
        # 图片缓存目录
        self.image_cache_dir = webhook_config.get('image_cache_dir', 'images')
    
    def log(self, message: str):
        """统一的日志输出方法"""
        if self.log_callback:
            self.log_callback(message)  # 推送到前端

    def _rate_limit_wait(self, operation_name: str = "操作"):
        """频率限制：随机等待 30-60 秒"""
        current_time = time.time()
        elapsed = current_time - self.last_operation_time
        
        # 随机等待时间
        wait_time_random = random.randint(self.rate_limit_min, self.rate_limit_max)
        
        if elapsed < wait_time_random:
            wait_time = wait_time_random - elapsed
            self.log(f"⏳ {operation_name}频率限制，等待 {wait_time:.0f} 秒...")
            time.sleep(wait_time)
        
        self.last_operation_time = time.time()

    def is_group_enabled(self, group_id: str) -> bool:
        """检查群组是否启用 webhook"""
        webhook_config = self.config.get('wecom_webhook', {})
        groups_config = webhook_config.get('groups', {})
        
        if group_id in groups_config:
            return groups_config[group_id].get('enabled', False)
        
        # 如果群组未配置，默认不启用
        return False

    # 推送相关函数

    def send_text(self, content: str, mentioned_list: Optional[List[str]] = None) -> bool:
        """
        发送文本消息
        
        Args:
            content: 消息内容
            mentioned_list: @的用户列表（手机号），可选
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        if not self.webhook_url:
            self.log("⚠️ 企业微信webhook地址未配置")
            return False
        
        try:
            data = {
                "msgtype": "text",
                "text": {
                    "content": content
                }
            }
            
            if mentioned_list:
                data["text"]["mentioned_list"] = mentioned_list
            
            response = self.session.post(
                self.webhook_url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            result = response.json()
            if result.get("errcode") == 0:
                self.log("✅ 企业微信消息发送成功")
                return True
            else:
                self.log(f"❌ 企业微信消息发送失败: {result.get('errmsg')}")
                return False
                
        except Exception as e:
            self.log(f"❌ 企业微信消息发送异常: {e}")
            return False
    
    def send_markdown(self, content: str) -> bool:
        """
        发送markdown格式消息
        
        Args:
            content: markdown格式的内容
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        if not self.webhook_url:
            self.log("⚠️ 企业微信webhook地址未配置")
            return False
        
        try:
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }
            
            response = self.session.post(
                self.webhook_url,
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            result = response.json()
            if result.get("errcode") == 0:
                self.log("✅ 企业微信消息发送成功")
                return True
            else:
                self.log(f"❌ 企业微信消息发送失败: {result.get('errmsg')}")
                return False
                
        except Exception as e:
            self.log(f"❌ 企业微信消息发送异常: {e}")
            return False
    
    def send_file(self, file_path: str) -> bool:
        """
        发送文件消息
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        if not self.webhook_url:
            self.log("⚠️ 企业微信webhook地址未配置")
            return False
        
        try:
            # 1. 上传文件获取media_id
            # 从webhook_url中提取key
            # webhook_url格式: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxx
            upload_url = self.webhook_url.replace('/send?', '/upload_media?') + '&type=file'
            
            # 准备文件上传参数
            file_name = os.path.basename(file_path)
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                self.log(f"❌ 文件不存在: {file_path}")
                return False
            
            # 检查文件大小（企业微信限制：文件大小不超过20MB）
            file_size = os.path.getsize(file_path)
            # ⭐ 新增：检查空文件
            if file_size == 0:
                self.log(f"❌ 文件为空（0字节）: {file_path}")
                return False
            if file_size > 20 * 1024 * 1024:  # 20MB
                self.log(f"❌ 文件大小超过限制（20MB）: {file_size} bytes")
                return False
            
            # 上传文件
            with open(file_path, "rb") as f:
                # 注意字段名必须是"media"
                response = self.session.post(
                    upload_url,
                    files={"media": (file_name, f)},
                    timeout=30
                )
            
            upload_result = response.json()
            if upload_result.get("errcode") != 0:
                self.log(f"❌ 文件上传失败: {upload_result.get('errmsg')}")
                return False
            
            media_id = upload_result.get("media_id")
            if not media_id:
                self.log("❌ 未获取到media_id")
                return False
            
            self.log(f"✅ 文件上传成功，media_id: {media_id}")
            
            # 2. 使用media_id发送文件
            payload = {
                "msgtype": "file",
                "file": {
                    "media_id": media_id
                }
            }
            
            response = self.session.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            result = response.json()
            if result.get("errcode") == 0:
                self.log("✅ 企业微信文件发送成功")
                return True
            else:
                self.log(f"❌ 企业微信文件发送失败: {result.get('errmsg')}")
                return False
                
        except FileNotFoundError:
            self.log(f"❌ 文件不存在: {file_path}")
            return False
        except Exception as e:
            self.log(f"❌ 企业微信文件发送异常: {e}")
            return False
    
    def process_topics(self, topics: List[Dict], stats: Dict = None, crawler=None) -> bool:
        """
        处理话题（只推送纯文字内容）
        
        处理逻辑：
        A. inline_article_url -> 爬取文章 -> PDF -> 水印 -> 加密 -> 改名 -> 下载本地（不推送）
        B. 有附件 -> 下载 -> 水印(如果是PDF) -> 加密 -> 下载本地（不推送）
        C. 有图片 -> 缓存缩略图和高清图 -> 下载本地（不推送）
        D. 纯文字 -> 前20字 + 访问链接 -> 推送文字消息
        """
        # 1. 检查群组是否启用
        group_id = crawler.group_id if crawler else None
        if not self.is_group_enabled(group_id):
            self.log(f"⚠️ 群组 {group_id} 未启用，跳过处理")
            return False
        
        if not topics:
            return False
        
        success_count = 0
        
        for i, topic in enumerate(topics, 1):
            try:
                talk = topic.get('talk', {})
                content = talk.get('text', '')
                
                # 提取元素
                article_url = self._extract_article_url(talk, topic)
                topic_files = talk.get('files', [])
                
                # ========== 分支A: inline_article_url ==========
                if article_url and 'zsxq' in article_url and crawler:
                    self._rate_limit_wait("文章爬取")
                    self.log(f"📄 第{i}/{len(topics)}条：检测到文章链接")
                    
                    # 处理文章链接
                    if self.handle_article_pdf(article_url, topic, crawler):
                        success_count += 1
                    
                    # 如果同时有附件，继续处理
                    if topic_files and crawler:
                        self._rate_limit_wait("附件下载")
                        self.log(f"   📎 继续处理附件...")
                        self.handle_attachments(topic_files, crawler)
                    
                    # 如果同时有图片，继续缓存
                    self.handle_images(talk, group_id)
                    
                    continue
                
                # ========== 分支B: 有附件 ==========
                if topic_files and crawler:
                    self._rate_limit_wait("附件下载")
                    self.log(f"📎 第{i}/{len(topics)}条：检测到附件（共{len(topic_files)}个）")
                    
                    # 处理附件
                    if self.handle_attachments(topic_files, crawler):
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
                
                # ========== 分支D: 纯文字内容 ==========
                if content:
                    self.log(f"📝 第{i}/{len(topics)}条：检测到纯文字内容")
                    if self.handle_text_content(content, group_id):
                        success_count += 1
                    
            except Exception as e:
                self.log(f"❌ 第{i}条处理异常: {e}")
                import traceback
                traceback.print_exc()
        
        self.log(f"📊 处理总结：{success_count}/{len(topics)}条成功")
        return success_count > 0
    

    # 工具函数

    def handle_text_content(self, content: str, group_id: str) -> bool:
        """
        处理文本内容并推送
        
        格式：前20字 + 访问链接 -> 推送文字消息
        """
        try:
            # 清理HTML标签
            content_clean = HTMLTagRemover.clean_html_tags(content)
            
            # 截取前30字
            content_preview = content_clean[:30] if len(content_clean) > 30 else content_clean
            
            # 格式：前20字... + 详细内容链接
            push_text = f"{content_preview}...\n\n详细内容：请访问：http://149.104.30.138:3080/groups/{group_id}"
            
            self.log(f"📝 处理文本内容...")
            
            # 使用现有的 send_text 方法推送
            if self.send_text(push_text):
                self.log(f"   ✅ 文字推送成功")
                return True
            else:
                self.log(f"   ❌ 文字推送失败")
                return False
                
        except Exception as e:
            self.log(f"   ❌ 文本处理失败: {e}")
            return False


    def handle_attachments(self, topic_files: List[Dict], crawler) -> bool:
        """
        处理附件（不推送）
        
        流程：下载 -> 水印(如果是PDF) -> 加密 -> 保存本地
        """
        try:
            self.log(f"📎 开始处理附件（共{len(topic_files)}个）")
            
            downloader = crawler.get_file_downloader()
            processed_count = 0
            
            for idx, file_info in enumerate(topic_files, 1):
                try:
                    # 获取文件名
                    file_name = file_info.get('name', 'Unknown')
                    safe_filename = "".join(c for c in file_name if c.isalnum() or c in '._-（）()[]{}' or '\u4e00' <= c <= '\u9fff')
                    if not safe_filename:
                        safe_filename = f"file_{file_info.get('id', 'unknown')}"
                    
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
                    
                    # 处理PDF文件
                    if source_path.lower().endswith('.pdf'):
                        self.log(f"   🖼️ 处理PDF: {safe_filename}")
                        
                        # 创建临时文件
                        temp_processed = source_path.replace('.pdf', '_temp.pdf')
                        
                        # 步骤1: 添加背景和水印
                        if not self._add_background_and_noise_to_pdf(source_path, temp_processed, group_id=crawler.group_id):
                            self.log(f"   ⚠️ 水印添加失败，使用源文件")
                            temp_processed = source_path
                        
                        # 步骤2: 加密
                        self._encrypt_pdf(temp_processed)
                        
                        # 步骤3: 用处理后的文件覆盖源文件
                        shutil.move(temp_processed, source_path)
                        
                        self.log(f"   ✅ PDF处理完成: {safe_filename}")
                        processed_count += 1
                    else:
                        # 非PDF文件，不处理
                        self.log(f"   ✅ 文件已下载: {safe_filename}")
                        processed_count += 1
                    
                    # 单个附件之间随机间隔（30-60秒）
                    if idx < len(topic_files):
                        self._rate_limit_wait("附件下载")
                        
                except Exception as e:
                    self.log(f"   ❌ 附件处理异常: {e}")
                    import traceback
                    traceback.print_exc()
            
            self.log(f"   ✅ 附件处理完成：{processed_count}/{len(topic_files)}个")
            return processed_count > 0
            
        except Exception as e:
            self.log(f"   ❌ 附件处理失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def handle_images(self, talk: Dict, group_id: str = None) -> Tuple[int, int]:
        """
        处理图片（不推送）
        
        流程：提取图片URL -> 缓存缩略图和高清图 -> 保存本地
        """
        from image_cache_manager import get_image_cache_manager
        
        # 提取图片URL
        images = []
        
        # 方法1: 从talk.images字段提取
        if 'images' in talk:
            image_list = talk.get('images', [])
            for img in image_list:
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
                article_images = article.get('images', [])
                for img in article_images:
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
                import re
                img_pattern = r'https?://[^\s<>"]+?(?:\.jpg|\.jpeg|\.png|\.gif|\.webp)'
                found_urls = re.findall(img_pattern, article_content, re.IGNORECASE)
                images.extend(found_urls)
        
        # 去重
        images = list(dict.fromkeys(images))
        
        if not images:
            return (0, 0)
        
        self.log(f"📷 开始处理图片（共{len(images)}张）")
        
        # 缓存图片
        cache_manager = get_image_cache_manager(group_id)
        cached_count = 0
        
        for idx, img_url in enumerate(images, 1):
            self.log(f"   📷 处理图片 {idx}/{len(images)}")
            
            # 下载原图
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
            
            # 单张图片之间随机间隔（30-60秒）
            if idx < len(images):
                self._rate_limit_wait("图片缓存")
        
        self.log(f"   ✅ 图片处理完成：{cached_count}/{len(images)}张")
        return (cached_count, len(images))

    def handle_article_pdf(self, article_url: str, topic: Dict, crawler) -> bool:
        """
        处理文章链接（不推送）
        
        流程：爬取 -> PDF -> 水印 -> 加密 -> 改名 -> 保存本地
        """
        try:
            title = topic.get('title', '无标题')
            topic_files = topic.get('talk', {}).get('files', [])
            
            self.log(f"📄 开始处理文章链接...")
            
            # 检查是否已有PDF
            if topic_files:
                for file_info in topic_files:
                    local_path = file_info.get('local_path', '')
                    if local_path and local_path.endswith('.pdf') and os.path.exists(local_path):
                        self.log(f"   ✅ 已存在PDF: {os.path.basename(local_path)}")
                        return True
            
            # 获取PDF输出目录
            pdf_output_dir = self._get_pdf_output_dir(crawler)
            
            # 爬取网页生成PDF
            pdf_path = self.convert_url_to_pdf(article_url, pdf_output_dir, title, cookie=crawler.cookie)
            
            if pdf_path:
                # 添加背景和干扰
                temp_pdf_path = pdf_path.replace('.pdf', '_temp_with_bg.pdf')
                if self._add_background_and_noise_to_pdf(pdf_path, temp_pdf_path, group_id=crawler.group_id):
                    # 加密
                    self._encrypt_pdf(temp_pdf_path)
                    
                    # 用处理后的文件覆盖原文件
                    shutil.move(temp_pdf_path, pdf_path)

                    self.log(f"   ✅ PDF处理完成: {os.path.basename(pdf_path)}")
                    return True
                else:
                    # 失败时仍然加密原文件
                    self._encrypt_pdf(pdf_path)
                    self.log(f"   ✅ PDF处理完成: {os.path.basename(pdf_path)}")
                    return True
            
            self.log(f"   ❌ PDF生成失败")
            return False
            
        except Exception as e:
            self.log(f"   ❌ 文章处理失败: {e}")
            import traceback
            traceback.print_exc()
            return False


    # inline_article_url处理        
    def _extract_article_url(self, talk: Dict, topic: Dict) -> Optional[str]:
        """提取文章链接"""
        # 优先从talk.article中获取链接
        if talk and 'article' in talk:
            article_data = talk.get('article', {})
            article_url = article_data.get('inline_article_url') or article_data.get('article_url')
            if article_url:
                return article_url
        
        # 从topic顶层获取链接
        return topic.get('inline_article_url') or topic.get('article_url')
    

    def _html_wrap_content(self, html_content: str, width: int = 46) -> str:
        """
        对 HTML 中的文本内容进行换行处理，链接单独一行显示,避免 PDF 生成时文本溢出
        """
        try:
            parts = re.split(r'(<[^>]+>)', html_content)
            result = []
            
            for part in parts:
                if part.startswith('<') and part.endswith('>'):
                    # 已经是HTML标签，检查是否是<a>标签
                    if part.startswith('<a ') or part.startswith('</a>'):
                        # 链接标签前后添加换行
                        result.append('<br>' + part + '<br>')
                    else:
                        result.append(part)
                else:
                    if part.strip():
                        # ⭐ 处理纯文本中的URL（非<a>标签包裹的链接）
                        # 匹配 http:// 或 https:// 开头的URL
                        part = re.sub(r'(https?://[^\s<>"\'\)]+)', r'<br>\1<br>', part)
                        
                        # 普通文本换行
                        wrapped = textwrap.fill(part, width=width)
                        result.append(wrapped.replace('\n', '<br>'))
                    else:
                        result.append(part)
            
            # 清理多余的连续<br>
            html_result = ''.join(result)
            html_result = re.sub(r'(<br>\s*){2,}', '<br>', html_result)
            
            return html_result
        except Exception as e:
            self.log(f"   ⚠️ 文本换行处理失败: {e}")
            return html_content


    def convert_url_to_pdf(self, url: str, output_dir: str, title: str = None, cookie: str = None) -> Optional[str]:
        """
        使用xhtml2pdf将网页URL转换为PDF文件（分支1使用）
        支持知识星球内部链接和外部链接
        
        Args:
            url: 网页URL
            output_dir: PDF输出目录
            title: 可选的文章标题
            cookie: 知识星球Cookie（用于访问知识星球内部文章）
                
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
            
            # 通用Edge浏览器headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
            
            # ✅ 判断域名类型，添加知识星球Cookie
            parsed_url = urlparse(url)
            domain = parsed_url.netloc
            
            if "zsxq.com" in domain or "wx.zsxq.com" in domain:
                self.log(f"   🔗 检测到知识星球域名，使用知识星球Cookie")
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
            
            self.log(f"   ✅ 获取到HTML内容: {len(html_content)} 字符")
            
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
            
            # 清理多余内容
            html_content = re.sub(r'<div[^>]*milkdown-preview[^>]*>.*?</div>', '', html_content, flags=re.DOTALL)
            
            # 使用xhtml2pdf转换
            self.log(f"   🔍 开始使用xhtml2pdf转换PDF...")
            
            html_content = re.sub(r'<\?xml[^>]*\?>\s*', '', html_content)
            html_content = re.sub(r'<!DOCTYPE[^>]*>\s*', '', html_content)
            html_content = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n' + html_content
            
            # 文本换行处理
            html_content = self._html_wrap_content(html_content, width=46)
            
            # 清理HTML结构
            html_content = re.sub(r'<p>\s*</p>', '', html_content)
            html_content = re.sub(r'<p([^>]*)>\s*(<img[^>]+>)\s*</p>', r'\2', html_content, flags=re.IGNORECASE)
            html_content = re.sub(r'</p>\s*<p>', '<br>', html_content)
            html_content = re.sub(r'(<br>\s*){2,}', '<br>', html_content)
            
            # 注入CSS样式
            css = '''
                <style>
                    @page { size: A4; margin: 2cm; }
                    body { 
                        font-family: STSong-Light, SimSun,Times New Roman, Arial, sans-serif; 
                        line-height: 1.6; 
                        margin: 0; 
                        padding: 15px; 
                        font-size: 12pt; 
                        word-wrap: break-word; 
                        word-break: break-word;
                    }
                    img { max-width: 100% !important; height: auto !important; display: block; margin: 10px 0; }
                    p, div { margin: 0.1em 0; padding: 0.2em 0; word-wrap: break-word; overflow-wrap: break-word; }
                    pre, code { white-space: pre-wrap; word-wrap: break-word; overflow-wrap: break-word; }
                    table { max-width: 100%; word-wrap: break-word; }
                    h1, h2, h3, h4, h5, h6 { margin: 1em 0 0.5em 0; font-weight: bold; word-wrap: break-word; }
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
            import traceback
            traceback.print_exc()
            return None


    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def _get_pdf_output_dir(self, crawler) -> str:
        
        # 根据下载配置决定PDF保存位置
        config = load_config()
        download_config = config.get('download', {})
        download_dir = download_config.get('dir', 'downloads')
        
        if download_dir == "downloads":
            # 使用默认目录结构：group_dir/downloads
            path_manager = get_db_path_manager()
            group_dir = path_manager.get_group_dir(crawler.group_id)
            pdf_dir = os.path.join(group_dir, 'downloads')
        else:
             # 使用自定义目录：download_dir/group_{group_id}
            pdf_dir = os.path.join(download_dir, f"group_{crawler.group_id}")
            
        # 确保目录存在
        os.makedirs(pdf_dir, exist_ok=True)
        
        # ⭐ 添加返回语句
        return pdf_dir


    def _add_background_and_noise_to_pdf(self, source_pdf: str, output_pdf: str, 
                                         group_id: str = None) -> bool:
        """
        为 PDF 添加背景图和干扰功能
        
        核心原则：保持源PDF尺寸不变，背景图适配
        """
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
            noise_text = "（原作者微信：MK0914666）"
            font_path = r"C:\Windows\Fonts\msyh.ttc"
            font_size = 10
            font_color = (0, 0, 0)  # 黑色
            insert_times = 3  # 固定插入3次
            
            for page_num in range(len(src_doc)):
                src_page = src_doc[page_num]
                src_w = src_page.rect.width
                src_h = src_page.rect.height
                
                # 创建与源PDF相同尺寸的页面
                out_page = out_doc.new_page(width=src_w, height=src_h)
                
                # 插入背景图（缩放到页面尺寸）
                if bg_image:
                    temp_bg_path = os.path.join(temp_dir, f"bg_{page_num}.png")
                    resized_bg = bg_image.resize((int(src_w), int(src_h)), Image.Resampling.LANCZOS)
                    resized_bg.save(temp_bg_path)
                    out_page.insert_image(fitz.Rect(0, 0, src_w, src_h), filename=temp_bg_path)
                    try:
                        os.remove(temp_bg_path)
                    except:
                        pass
                
                # 插入源PDF内容（不缩放，直接覆盖）
                out_page.show_pdf_page(
                    fitz.Rect(0, 0, src_w, src_h),
                    src_doc,
                    page_num
                )
                
                # ============ 添加干扰文字 ============
                for _ in range(insert_times):
                    # 随机位置
                    noise_x = random.randint(30, max(31, int(src_w) - 150))
                    noise_y = random.randint(50, max(51, int(src_h) - 50))
                    
                    out_page.insert_text(
                        fitz.Point(noise_x, noise_y),
                        noise_text,
                        fontname="china-s",  # 使用内置简体中文字体
                        fontfile=font_path,
                        fontsize=font_size,
                        color=font_color
                    )
                
                self.log(f"   📄 第{page_num+1}页: {src_w:.0f}x{src_h:.0f}, 已添加{insert_times}处干扰文字")
            else:
                self.log(f"   📄 第{page_num+1}页: {src_w:.0f}x{src_h:.0f}")
            
            # 保存
            out_doc.save(output_pdf)
            out_doc.close()
            src_doc.close()
            
            self.log(f"   ✅ 背景和干扰添加完成")
            return True
            
        except Exception as e:
            self.log(f"   ❌ 背景添加失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _encrypt_pdf(self, pdf_path: str, owner_password: str = "protect_pdf@Arron") -> bool:
        """
        使用 PyMuPDF 对 PDF 进行加密保护
        用户无需密码即可打开查看，但无法修改、复制、导出

        Args:
            pdf_path: PDF 文件路径
            owner_password: 所有者密码（用于修改权限）

        Returns:
            是否成功
        """
        try:
            doc = fitz.open(pdf_path)

            # PyMuPDF 权限值（设置为0表示禁止所有操作，只允许查看）
            # 权限值定义：允许的操作的组合
            # 0 = 只读，禁止所有操作
            perm = 0

            # 加密保存（用户密码为空，允许无密码打开）
            temp_path = pdf_path + ".encrypted"
            doc.save(
                temp_path,
                encryption=fitz.PDF_ENCRYPT_AES_256,  # AES-256 加密
                owner_pw=owner_password,              # 所有者密码
                user_pw="",                           # 用户密码为空
                permissions=perm                      # 权限：只读
            )
            doc.close()

            # 替换原文件
            os.replace(temp_path, pdf_path)

            self.log(f"   🔒 PDF加密完成（禁止修改/复制/导出）")
            return True

        except Exception as e:
            self.log(f"   ❌ PDF加密失败: {e}")
            import traceback
            traceback.print_exc()
            return False

