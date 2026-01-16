"""
企业微信Webhook推送模块
用于在爬取到新内容后推送通知
"""
import requests
import json
import os
import re
from typing import Dict, List, Optional
from html.parser import HTMLParser
from db_path_manager import get_db_path_manager
from zsxq_interactive_crawler import load_config

from zsxq_interactive_crawler import load_config
from PyPDF2 import PdfReader, PdfWriter
import traceback
import hashlib


class HTMLTagRemover(HTMLParser):
    """HTML标签清理器"""
    def __init__(self):
        super().__init__()
        self.result = []
    
    def handle_data(self, data):
        self.result.append(data)
    
    def get_text(self):
        return ''.join(self.result)


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
    
    def __init__(self, webhook_url: str, enabled: bool = True, log_callback=None):
        """
        初始化企业微信Webhook
        
        Args:
            webhook_url: 企业微信机器人webhook地址
            enabled: 是否启用推送
        """
        self.webhook_url = webhook_url
        self.enabled = enabled
        self.session = requests.Session()
        self.log_callback = log_callback  # ✅ 添加日志回调
    
    def log(self, message: str):
        """统一的日志输出方法"""
        if self.log_callback:
            self.log_callback(message)  # 推送到前端
    
    def add_watermark_to_pdf(self, pdf_path: str, watermark_pdf_path: str = None) -> bool:
        """
        使用PyPDF2为PDF添加水印
        
        Args:
            pdf_path: PDF文件路径（会被原地修改）
            watermark_pdf_path: 水印PDF路径，如果为None则使用默认路径
            
        Returns:
            是否成功
        """
        try:
            # 水印PDF文件路径（硬编码）
            watermark_pdf_path = r"E:/zsxq/ZsxqCrawler-wxpush/output/databases/28858542222551/downloads/watermark.pdf"
            
            # 检查水印PDF是否存在
            if not os.path.exists(watermark_pdf_path):
                self.log(f"   ⚠️ 水印文件不存在，跳过添加水印: {watermark_pdf_path}")
                return False
            
            self.log(f"   🔖 开始添加水印...")
            self.log(f"   📄 PDF文件: {pdf_path}")
            self.log(f"   🖼️ 水印文件: {watermark_pdf_path}")
            
            # 读取原始PDF
            reader = PdfReader(pdf_path)
            writer = PdfWriter()
            
            # 读取水印PDF（只读取第一页）
            watermark_reader = PdfReader(watermark_pdf_path)
            watermark_page = watermark_reader.pages[0]
            
            # 遍历每一页，合并水印
            page_count = len(reader.pages)
            for i, page in enumerate(reader.pages, 1):
                # 合并水印到当前页面
                page.merge_page(watermark_page)
                writer.add_page(page)
                
                # 进度日志
                if page_count <= 10 or i % 10 == 0 or i == page_count:
                    self.log(f"   📄 处理进度: {i}/{page_count} 页")
            
            # 保存带水印的PDF（覆盖原文件）
            with open(pdf_path, 'wb') as output_file:
                writer.write(output_file)
            
            self.log(f"   ✅ 水印添加完成: {pdf_path}")
            return True
            
        except Exception as e:
            self.log(f"   ❌ 添加水印失败: {e}")
            self.log(f"   📋 异常详情:\n{traceback.format_exc()}")
            return False

    
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
    
    def send_new_topics_notification(self, new_topics: List[Dict], stats: Dict, crawler=None) -> bool:
        """
        发送新话题推送通知
        
        Args:
            new_topics: 新话题列表
            stats: 统计信息
            crawler: 爬虫实例（用于转换PDF），必需
        Returns:
            是否发送成功
        """
        if not self.enabled or not new_topics:
            return False
        
        # ✅ 限制最多推送10个话题
        topics_to_send = new_topics[:10]
        if len(new_topics) > 10:
            self.log(f"⚠️ 话题数量超过10个，只推送前10个（总共{len(new_topics)}个）")
        
        success_count = 0
        
        # 添加前10个新话题的预览，为每个话题单独推送
        for i, topic in enumerate(topics_to_send, 1):
            try:
                title = topic.get('title', '无标题')
                # 内容在 talk.text 字段中
                talk = topic.get('talk', {})
                content = talk.get('text', '无内容')
                create_time = topic.get('create_time', '未知时间')
                # 作者信息在 talk.owner.name 字段中
                owner = talk.get('owner', {})
                author_name = owner.get('name', '六便士')
                
                # 提取文章链接
                article_url = self._extract_article_url(talk, topic)
                
                # 提取附件列表
                topic_files = talk.get('files', [])
                
                # ========== 2. 分支1: 有文章链接 → 转换PDF推送 ==========
                if article_url and crawler:
                    if self._handle_article_pdf(i, article_url, title, crawler, len(new_topics)):
                        success_count += 1
                    continue  # 已处理，跳过后续分支
                
                # ========== 3. 分支2: 有附件 → 下载推送 ==========
                if topic_files and crawler:
                    if self._handle_attachments(i, topic_files, title, crawler, len(new_topics)):
                        success_count += 1
                    continue  # 已处理，跳过后续分支
                
                # ========== 4. 分支3: 内容中有图片 → 下载图片，推送文本和图片 ==========
                content_images = self._extract_images(talk)
                if content_images and crawler:
                    # 先推送文本
                    text_success = self._handle_text_message(i, title, content, author_name, create_time, len(new_topics))
                    # 再推送图片
                    image_success = self._handle_images(i, content_images, title, crawler, len(new_topics))
                    # 只要有一个成功就算成功
                    if text_success or image_success:
                        success_count += 1
                    continue  # 已处理，跳过后续分支
                
                 # ========== 5. 分支4: 纯文本推送 ==========
                if self._handle_text_message(i, title, content, author_name, create_time, len(new_topics)):
                    success_count += 1
                    
            except Exception as e:
                self.log(f"❌ 第{i}条推送异常: {e}")
        
        # ✅ 添加推送总结日志
        if success_count == len(topics_to_send):
            self.log(f"📊 推送总结：{success_count}/{len(topics_to_send)}条全部成功")
        else:
            self.log(f"⚠️ 推送总结：{success_count}/{len(topics_to_send)}条成功")
        
        return success_count == len(topics_to_send)
                
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
    
    def _handle_article_pdf(self, index: int, article_url: str, title: str, crawler, total: int) -> bool:
        """处理文章PDF转换和推送（分支1）"""
        try:
            self.log(f"📄 第{index}/{total}条：检测到文章链接，开始转换PDF...")
            
            # 获取PDF输出目录
            pdf_output_dir = self._get_pdf_output_dir(crawler)
            
            # 转换PDF
            pdf_path = crawler.convert_url_to_pdf(article_url, pdf_output_dir, title)
            
            if pdf_path:
                # 添加水印（如果是PDF文件）
                if pdf_path.lower().endswith('.pdf'):
                    self.log(f"   🖼️ 检测到PDF文件，添加水印...")
                    self.add_watermark_to_pdf(pdf_path)
                
                # 发送PDF文件
                self.log(f"   📎 正在发送PDF文件...")
                if self.send_file(pdf_path):
                    self.log(f"   ✅ PDF发送成功")
                    return True
                else:
                    self.log(f"   ⚠️ PDF发送失败")
            else:
                self.log(f"   ⚠️ PDF转换失败")
            
            return False
        except Exception as e:
            self.log(f"   ❌ PDF处理异常: {e}")
            return False
    
    def _handle_attachments(self, index: int, topic_files: List[Dict], title: str, crawler, total: int) -> bool:
        """处理附件下载和推送（分支2）"""
        try:
            self.log(f"📎 第{index}/{total}条：检测到附件（共{len(topic_files)}个），开始下载...")
            
            # 获取文件下载器
            downloader = crawler.get_file_downloader()
            
            # 下载所有附件
            downloaded_count = 0
            pushed_count = 0
            for file_info in topic_files:
                try:
                    # 构造file_info字典
                    file_data = {'file': file_info}
                    
                    # 下载文件
                    result = downloader.download_file(file_data)
                    
                    if result == "skipped":
                        self.log(f"   ⏭️ 文件已存在，跳过: {file_info.get('name', 'Unknown')}")
                    elif result:  # ✅ 返回的是文件路径（字符串）
                        downloaded_count += 1
                        
                        # ✅ 获取文件信息（用于构造文件路径）
                        file_name = file_info.get('name', 'Unknown')
                        
                        # 清理文件名（移除非法字符）
                        safe_filename = "".join(c for c in file_name if c.isalnum() or c in '._-（）()[]{}')
                        
                        # ✅ 构造文件路径（与download_file中的逻辑一致）
                        file_path = os.path.join(downloader.download_dir, safe_filename)
                        
                        # ✅ 统一在这里推送到企业微信
                        # ✅ 检查文件是否存在
                        if os.path.exists(file_path):
                            # 添加水印（如果是PDF文件）
                            if file_path.lower().endswith('.pdf'):
                                self.log(f"   🖼️ 检测到PDF附件，添加水印...")
                                self.add_watermark_to_pdf(file_path)
                            
                            self.log(f"   📱 正在推送到企业微信: {file_info.get('name', 'Unknown')}")
                            if self.send_file(file_path):
                                self.log(f"   ✅ 企业微信推送成功")
                                pushed_count += 1
                            else:
                                self.log(f"   ⚠️ 企业微信推送失败")
                        else:
                            self.log(f"   ❌ 文件不存在: {file_path}")
                    else:
                        self.log(f"   ❌ 附件下载失败: {file_info.get('name', 'Unknown')}")
                except Exception as e:
                    self.log(f"   ❌ 附件处理异常: {e}")
            
            if downloaded_count > 0:
                self.log(f"   ✅ 附件处理完成：下载{downloaded_count}个，推送{pushed_count}个")
                return True
            else:
                self.log(f"   ⚠️ 所有附件已存在或下载失败，跳过推送")
                return False
            
        except Exception as e:
            self.log(f"   ❌ 附件处理异常: {e}")
            return False
    
    #图片相关推送处理
    def _extract_images(self, talk: Dict) -> List[str]:
        """
        从内容中提取图片URL列表
        
        Args:
            talk: 话题的talk字段
            
        Returns:
            图片URL列表
        """
        images = []
        
        # 方法1: 从talk.images字段提取
        if 'images' in talk:
            image_list = talk.get('images', [])
            for img in image_list:
                if isinstance(img, dict):
                    # 图片可能是对象，提取URL
                    img_url = img.get('original', {}).get('url')
                    if img_url:
                        images.append(img_url)
                elif isinstance(img, str):
                    # 图片是URL字符串
                    images.append(img)
        
        # 方法2: 从text字段中提取img标签
        text = talk.get('text', '')
        if text:
            # 匹配HTML中的img标签，提取src属性
            img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
            matches = re.findall(img_pattern, text, re.IGNORECASE)
            images.extend(matches)
        
        # 去重
        images = list(dict.fromkeys(images))
        
        return images

    def _download_image(self, image_url: str, save_dir: str, index: int = 0) -> Optional[str]:
        """
        下载图片到本地
        
        Args:
            image_url: 图片URL
            save_dir: 保存目录
            index: 次序编号（用于命名）
            
        Returns:
            图片文件路径，失败返回None
        """
        try:
            self.log(f"   📥 开始下载图片: {image_url}")
            
            # 确保保存目录存在
            os.makedirs(save_dir, exist_ok=True)
            
            # 下载图片
            response = self.session.get(image_url, timeout=30)
            if response.status_code != 200:
                self.log(f"   ❌ 图片下载失败: HTTP {response.status_code}")
                return None
            
            # 根据Content-Type确定扩展名
            content_type = response.headers.get('Content-Type', '')
            ext_map = {
                'image/jpeg': '.jpg',
                'image/jpg': '.jpg',
                'image/png': '.png',
                'image/gif': '.gif',
                'image/webp': '.webp',
                'image/bmp': '.bmp'
            }
            
            ext = '.jpg'  # 默认扩展名
            if content_type:
                for ct, e in ext_map.items():
                    if ct in content_type.lower():
                        ext = e
                        break
            
            # ✅ 使用hash值生成简短文件名
            # 对URL进行MD5 hash，取前8位
            hash_value = hashlib.md5(image_url.encode()).hexdigest()[:8]
            filename = f"{hash_value}_{index}{ext}"
            
            image_path = os.path.join(save_dir, filename)
            
            # 检查图片是否已存在
            if os.path.exists(image_path):
                self.log(f"   ✅ 图片已存在，跳过下载: {filename}")
                return image_path
            
            # 保存图片
            with open(image_path, 'wb') as f:
                f.write(response.content)
            
            file_size = os.path.getsize(image_path)
            self.log(f"   ✅ 图片下载成功: {filename} ({file_size/1024:.1f}KB)")
            
            return image_path
            
        except Exception as e:
            self.log(f"   ❌ 图片下载异常: {e}")
            return None

    def _handle_images(self, index: int, image_urls: List[str], title: str, 
                   crawler, total: int) -> bool:
        """
        处理图片下载和推送（只负责图片，不负责文本）
        
        Args:
            index: 当前话题索引
            image_urls: 图片URL列表
            title: 话题标题
            crawler: 爬虫实例
            total: 总话题数
            
        Returns:
            是否处理成功
        """
        try:
            self.log(f"🖼️ 第{index}/{total}条：检测到图片（共{len(image_urls)}张），开始下载...")
            
            # 获取下载目录
            pdf_output_dir = self._get_pdf_output_dir(crawler)
            
            # 下载图片
            downloaded_images = []
            for i, img_url in enumerate(image_urls, 1):
                try:
                    file_path = self._download_image(img_url, pdf_output_dir)
                    if file_path:
                        downloaded_images.append(file_path)
                    else:
                        self.log(f"   ❌ 图片{i}/{len(image_urls)}下载失败")
                except Exception as e:
                    self.log(f"   ❌ 图片{i}/{len(image_urls)}下载异常: {e}")
            
            if not downloaded_images:
                self.log(f"   ⚠️ 所有图片下载失败")
                return False
            
            # 推送图片（最多推前8张）
            max_images = min(len(downloaded_images), 8)
            pushed_count = 0
            for i in range(max_images):
                try:
                    self.log(f"   📱 正在推送图片{i+1}/{max_images}...")
                    if self.send_image(downloaded_images[i]):
                        self.log(f"   ✅ 图片{i+1}/{max_images}推送成功")
                        pushed_count += 1
                    else:
                        self.log(f"   ❌ 图片{i+1}/{max_images}推送失败")
                except Exception as e:
                    self.log(f"   ❌ 图片{i+1}/{max_images}推送异常: {e}")
            
            if pushed_count > 0:
                self.log(f"   ✅ 图片处理完成：下载{len(downloaded_images)}张，推送{pushed_count}张")
                return True
            else:
                self.log(f"   ⚠️ 图片推送失败")
                return False
                
        except Exception as e:
            self.log(f"   ❌ 图片处理异常: {e}")
            return False

    def send_image(self, image_path: str) -> bool:
        """
        发送图片消息（使用base64方式）
        
        Args:
            image_path: 图片文件路径
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        if not self.webhook_url:
            self.log("⚠️ 企业微信webhook地址未配置")
            return False
        
        try:
            # 检查文件是否存在
            if not os.path.exists(image_path):
                self.log(f"❌ 图片不存在: {image_path}")
                return False
            
            # 检查文件大小
            file_size = os.path.getsize(image_path)
            max_size = 2 * 1024 * 1024  # 2MB
            if file_size > max_size:
                self.log(f"❌ 图片大小超过2MB限制: {file_size/1024/1024:.2f}MB")
                return False
            
            self.log(f"   📷 正在发送图片: {os.path.basename(image_path)} ({file_size/1024:.1f}KB)")
            
            # 读取图片并转换为base64
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # 计算md5
            import hashlib
            md5_value = hashlib.md5(image_data).hexdigest()
            
            # 转换为base64
            import base64
            base64_data = base64.b64encode(image_data).decode('utf-8')
            
            # 构建消息体
            payload = {
                "msgtype": "image",
                "image": {
                    "base64": base64_data,
                    "md5": md5_value
                }
            }
            
            # 发送消息
            response = self.session.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            result = response.json()
            if result.get("errcode") == 0:
                self.log(f"   ✅ 图片发送成功")
                return True
            else:
                self.log(f"   ❌ 图片发送失败: {result.get('errmsg')}")
                return False
                
        except Exception as e:
            self.log(f"   ❌ 图片发送异常: {e}")
            return False
 
    def _handle_text_message(self, index: int, title: str, content: str, author_name: str, 
                           create_time: str, total: int) -> bool:
        """处理纯文本消息推送（分支3）"""
        try:
            # 清理HTML标签
            title = clean_html_tags(title)
            content = clean_html_tags(content)
            
            # 构建markdown消息
            lines = [
                "# 📣 大佳新内容通知",
                "",
                f"## {title}",
                "",
                f"👤 作者: {author_name}",
                f"⏰ 时间: {create_time}",
                "",
                f"📄 内容:",
                f"{content}",
                "",
                "---",
                f"*🤖 本内容由六便士整理推送 - 第{index}/{total}条*"
            ]
            
            markdown_content = "\n".join(lines)
            
            # 发送消息
            if self.send_markdown(markdown_content):
                self.log(f"✅ 第{index}/{total}条推送成功")
                return True
            else:
                self.log(f"❌ 第{index}/{total}条推送失败")
                return False
            
        except Exception as e:
            self.log(f"❌ 第{index}条文本推送异常: {e}")
            return False
