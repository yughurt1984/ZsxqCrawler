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
from PIL import Image, ImageDraw, ImageFont  # ✅ 添加PIL导入
import textwrap  # ✅ 添加文本换行支持
import random

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
                    self.log(f"🖼️ 第{i}/{len(new_topics)}条：检测到图片和文字，准备合并推送...")
                    
                    # 获取下载目录
                    pdf_output_dir = self._get_pdf_output_dir(crawler)
                    
                    # 下载所有图片
                    downloaded_images = []
                    for img_url in content_images:
                        img_path = self._download_image(img_url, pdf_output_dir)
                        if img_path:
                            downloaded_images.append(img_path)
                    
                    # 合并文本和图片为一张图片
                    if downloaded_images:
                        merged_image_path = self._text_and_images_to_image(
                            title=title,
                            content=content,
                            author_name=author_name,
                            create_time=create_time,
                            image_paths=downloaded_images,
                            index=i,
                            total=len(new_topics)
                        )
                        
                        if merged_image_path and self.send_image(merged_image_path):
                            self.log(f"✅ 第{i}/{len(new_topics)}条推送成功（合并图片）")
                            # 清理临时图片
                            for img_path in downloaded_images:
                                try:
                                    os.remove(img_path)
                                except:
                                    pass
                            try:
                                os.remove(merged_image_path)
                            except:
                                pass
                            success_count += 1
                        else:
                            self.log(f"❌ 第{i}/{len(new_topics)}条推送失败")
                    else:
                        self.log(f"❌ 第{i}/{len(new_topics)}条：所有图片下载失败")
                    
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

    def _text_and_images_to_image(self, title: str, content: str, author_name: str, 
                                 create_time: str, image_paths: List[str], 
                                 index: int, total: int) -> Optional[str]:
        """
        将文本内容和图片合并成一张图片
        
        Args:
            title: 标题
            content: 内容
            author_name: 作者名
            create_time: 创建时间
            image_paths: 图片路径列表
            index: 当前索引
            total: 总数
            
        Returns:
            图片文件路径，失败返回None
        """
        try:
            # 清理HTML标签
            title = clean_html_tags(title)
            content = clean_html_tags(content)
            
            # 创建图片（白色背景）
            img_width = 750  # 减小图片宽度
            # 根据内容动态计算高度，先创建一个临时图片用于计算
            background_color = (255, 255, 255)  # 白色
            temp_image = Image.new('RGB', (img_width, 100), background_color)
            temp_draw = ImageDraw.Draw(temp_image)
        
            
            # 尝试加载字体
            font_paths = [
            "C:\\Windows\\Fonts\\simhei.ttf",  # 黑体：更清晰锐利
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simsun.ttc",
                None
            ]
            
            font_title = None
            font_text = None
            font_info = None
            
            for font_path in font_paths:
                try:
                    if font_path:
                        font_title = ImageFont.truetype(font_path, 40)
                        font_text = ImageFont.truetype(font_path, 30)
                        font_info = ImageFont.truetype(font_path, 20)
                        break
                except:
                    continue
            
            if font_title is None:
                font_title = ImageFont.load_default()
                font_text = ImageFont.load_default()
                font_info = ImageFont.load_default()
            
            # 先计算文字内容的实际行数
            max_content_width = img_width - 50  # 减小边距，增大内容宽度
            content_lines = []
            
            paragraphs = content.split('\n')
            for para in paragraphs:
                if para.strip():
                    current_line = ""
                    for char in para:
                        test_line = current_line + char
                        bbox = temp_draw.textbbox((0, 0), test_line, font=font_text)
                        line_width = bbox[2] - bbox[0]
                        
                        if line_width <= max_content_width:
                            current_line = test_line
                        else:
                            if current_line:
                                content_lines.append(current_line)
                            current_line = char
                    
                    if current_line:
                        content_lines.append(current_line)
                else:
                    content_lines.append("")
            
            # 动态计算图片高度
            # 固定部分高度：顶部横线(3)+间距(15)+标题(45)+副标题(40)+分隔线(2)+间距(20)+
            # 作者(20)+时间(20)+间距(25)+分割线(1)+间距(15)+内容标签(20)+间距(20)
            fixed_height = 236
            # 内容部分高度（增大行间距到28）
            content_height = len(content_lines) * 40 # 每行28像素
            # 图片部分高度（每行2张，固定尺寸）
            fixed_img_w = (img_width - 50) // 2 - 10  # 每张图片宽度，减去左右边距和间距
            fixed_img_h = 180  # 固定图片高度
            
            if image_paths:
                # 计算图片行数：每行2张
                num_images = len(image_paths)
                image_rows = (num_images + 1) // 2  # 向上取整
                # 分割线(1)+间距(15)+标签(30)+间距(15)+图片行数×(高度+间距)
                image_height = 1 + 15 + 30 + 15 + image_rows * (fixed_img_h + 15)
            else:
                image_height = 0
            # 底部信息高度：间距(15)+分割线(1)+间距(20)+底部文字(30)
            footer_height = 66
            
            # 总高度
            img_height = fixed_height + content_height + image_height + footer_height
            # 确保最小高度
            img_height = max(img_height, 800)
            
            # 创建实际图片
            image = Image.new('RGB', (img_width, img_height), background_color)
            draw = ImageDraw.Draw(image)
        
            # 颜色定义
            title_color = (0, 0, 0)
            text_color = (70, 70, 70)
            info_color = (100, 100, 100)
            border_color = (200, 200, 200)
            
            # 当前Y坐标
            y = 40
            
            # 绘制顶部横线
            draw.rectangle([20, y, img_width - 20, y + 3], fill=border_color)
            y += 15
            
            # 绘制标题
            title_text = "大佳新内容推送"
            bbox = draw.textbbox((0, 0), title_text, font=font_title)
            title_width = bbox[2] - bbox[0]
            draw.text(((img_width - title_width) // 2, y), title_text, 
                    fill=title_color, font=font_title)
            y += 50
            
            # 绘制分隔线
            draw.line([25, y, img_width - 40, y], fill=border_color, width=2)
            y += 25
            
            # 绘制作者和时间
            draw.text((25, y), f" 作者: {author_name}", 
                    fill=info_color, font=font_info)
            y += 25
            draw.text((25, y), f" 时间: {create_time}", 
                    fill=info_color, font=font_info)
            y += 30
            
            # 在时间和内容之间添加分割线
            draw.line([25, y, img_width - 40, y], fill=border_color, width=1)
            y += 20
            
            # 绘制内容标签
            draw.text((25, y), " 内容:", fill=info_color, font=font_info)
            y += 25
            
            # 绘制所有内容（不限制行数），增大行间距
            for line in content_lines:
                if line:
                    draw.text((25, y), line, fill=text_color, font=font_text, stroke_width=1, stroke_fill=(240, 240, 240))
                y += 40  # 增大行间距从22到40
                        
            
            # 绘制图片（网格布局，每行2张）
            if image_paths:
                y += 20
                draw.line([25, y, img_width - 25, y], fill=border_color, width=1)
                y += 15
                draw.text((25, y), f" 图片 ({len(image_paths)}张):", fill=info_color, font=font_info)
                y += 30
                
            # 固定图片尺寸
            fixed_img_w = (img_width - 50) // 2 - 10  # 每张图片宽度，减去边距和间距
            fixed_img_h = 180  # 固定图片高度
            
            # 网格布局：每行2张图片
            left_margin = 25
            col_width = fixed_img_w + 10  # 图片宽度 + 间距
            
            # 记录图片区域的起始Y坐标
            image_start_y = y
            
            for i, img_path in enumerate(image_paths):
                try:
                    img = Image.open(img_path)
                    # 固定图片尺寸，使用缩放模式（contain模式：完整显示）
                    img_w, img_h = img.size
                    
                    # 计算缩放比例（contain模式：完整显示图片）
                    ratio_w = fixed_img_w / img_w
                    ratio_h = fixed_img_h / img_h
                    ratio = min(ratio_w, ratio_h)  # 使用较小的比例，确保完整显示
                    
                    # 缩放到固定尺寸内
                    new_w = int(img_w * ratio)
                    new_h = int(img_h * ratio)
                    img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    
                    # 计算位置（每行2张）
                    row = i // 2
                    col = i % 2
                    
                    # 计算该行的Y坐标
                    if row == 0:
                        current_y = image_start_y
                    else:
                        current_y = image_start_y + row * (fixed_img_h + 15)
                    
                    x = left_margin + col * col_width
                    
                    # 计算居中偏移（使图片在固定区域内居中）
                    offset_x = (fixed_img_w - new_w) // 2
                    offset_y = (fixed_img_h - new_h) // 2
                    
                    # 绘制图片边框（固定尺寸）
                    draw.rectangle([x, current_y, x + fixed_img_w, current_y + fixed_img_h], 
                              fill=border_color, width=1)
                    
                    # 绘制图片（居中放置在固定区域内）
                    image.paste(img_resized, (x + offset_x, current_y + offset_y))
                    
                    self.log(f"   ✅ 已嵌入图片{i+1}/{len(image_paths)} (原始:{img_w}x{img_h} -> 缩放:{new_w}x{new_h})")
                except Exception as e:
                    self.log(f"   ❌ 嵌入图片{i+1}失败: {e}")

                
                # 更新Y坐标到图片区域的底部
                num_images = len(image_paths)
                image_rows = (num_images + 1) // 2
                y += fixed_img_h + 15  # 移动到最后一行图片的底部
            
            else:
                # 没有图片时，记录当前y位置
                last_image_y = y
            
            # 添加旋转45度水印"六便士出品"（在最后一张图片位置，最上层）
            try:
                watermark_text = "六便士出品，欢迎联系作者微信：yughurt1984"
                watermark_font_size = 32
                
                # 尝试加载字体
                try:
                    watermark_font = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", watermark_font_size)
                except:
                    watermark_font = ImageFont.load_default()
                
                # 计算水印文字的尺寸
                temp_draw = ImageDraw.Draw(image)
                watermark_bbox = temp_draw.textbbox((0, 0), watermark_text, font=watermark_font)
                watermark_w = watermark_bbox[2] - watermark_bbox[0]
                watermark_h = watermark_bbox[3] - watermark_bbox[1]
                
                # 创建一个足够大的临时图片来容纳旋转后的水印
                diagonal = int((watermark_w ** 2 + watermark_h ** 2) ** 0.5) + 40
                watermark_img = Image.new('RGBA', (diagonal, diagonal), (255, 255, 255, 0))
                watermark_draw = ImageDraw.Draw(watermark_img)
                
                # 在临时图片中心绘制水印文字（调淡颜色）
                watermark_color = (180, 180, 180, 150)  # 浅灰色，透明度150
                text_x = (diagonal - watermark_w) // 2
                text_y = (diagonal - watermark_h) // 2
                watermark_draw.text((text_x, text_y), watermark_text, 
                                 fill=watermark_color, font=watermark_font)
                
                # 旋转45度
                watermark_img = watermark_img.rotate(45, expand=False)
                
                # 计算水印位置：在最后一张图片起始位置的斜45°方向
                # 水印位置以最后一张图片的起始位置为基准
                watermark_base_x = img_width // 2  # 水平居中
                watermark_base_y = last_image_y if last_image_y else y  # 最后一张图片的Y坐标
                
                # 水印位于基准位置的斜45°上方
                # 向右下45°方向偏移
                offset_x = 10   # 水平偏移（向右）
                offset_y = -200  # 垂直偏移（向上，负值表示向上）
                watermark_x = watermark_base_x - diagonal // 2 + offset_x
                watermark_y = watermark_base_y - diagonal // 2 + offset_y
                
                # 将水印粘贴到主图片上（最上层）
                image.paste(watermark_img, (watermark_x, watermark_y), watermark_img)
                
                self.log(f"   ✅ 已添加水印: {watermark_text} 位置({watermark_x}, {watermark_y})")
            except Exception as e:
                self.log(f"   ⚠️ 添加水印失败: {e}")
                import traceback
                self.log(f"   详细错误: {traceback.format_exc()}")    
            
            # 绘制底部信息
            y += 15
            draw.line([25, y, img_width - 40, y], fill=border_color, width=1)
            y += 20
            
            footer_text = "🤖 本内容由六便士整理推送"
            footer_bbox = draw.textbbox((0, 0), footer_text, font=font_info)
            footer_width = footer_bbox[2] - footer_bbox[0]
            draw.text(((img_width - footer_width) // 2, y), footer_text, 
                    fill=info_color, font=font_info)
            
            # 保存图片
            temp_dir = os.path.join(os.path.dirname(__file__), "temp_images")
            os.makedirs(temp_dir, exist_ok=True)
            
            import time
            timestamp = int(time.time() * 1000)
            image_filename = f"text_with_images_{timestamp}.png"
            image_path = os.path.join(temp_dir, image_filename)

            image.save(image_path, 'PNG', quality=95,dpi=(600, 600))
            
            self.log(f"   ✅ 文本和图片已合并: {image_path}")
            return image_path
            
        except Exception as e:
            self.log(f"   ❌ 文本和图片合并失败: {e}")
            import traceback
            traceback.print_exc()
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
    
    def _text_to_image(self, title: str, content: str, author_name: str, 
                   create_time: str, index: int, total: int) -> Optional[str]:
        """
        将文本内容转换为图片
        
        Args:
            title: 标题
            content: 内容
            author_name: 作者名
            create_time: 创建时间
            index: 当前索引
            total: 总数
            
        Returns:
            图片文件路径，失败返回None
        """
        try:
            # 创建图片（白色背景）
            img_width = 800
            img_height = 1000
            background_color = (255, 255, 255)  # 白色
            image = Image.new('RGB', (img_width, img_height), background_color)
            draw = ImageDraw.Draw(image)
            
            # 尝试加载字体，优先使用中文字体
            font_paths = [
            "C:\\Windows\\Fonts\\simhei.ttf",  # 黑体：更清晰锐利
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simsun.ttc",
                None  # 使用默认字体
            ]
            
            font_title = None
            font_text = None
            font_info = None
            
            for font_path in font_paths:
                try:
                    if font_path:
                        font_title = ImageFont.truetype(font_path, 40)
                        font_text = ImageFont.truetype(font_path, 30)
                        font_info = ImageFont.truetype(font_path, 20)
                        break
                except:
                    continue
            
            # 如果所有字体都加载失败，使用默认字体
            if font_title is None:
                font_title = ImageFont.load_default()
                font_text = ImageFont.load_default()
                font_info = ImageFont.load_default()
            
            # 颜色定义
            title_color = (0, 0, 0)  # 黑色
            text_color = (70, 70, 70)  # 深灰色
            info_color = (100, 100, 100)  # 灰色
            border_color = (200, 200, 200)  # 浅灰色
            
            # 当前Y坐标
            y = 30
            
            # 绘制顶部横线
            draw.rectangle([20, y, img_width - 20, y + 3], fill=border_color)
            y += 40  # ✅ 修改：增加间距，直接从作者信息开始
            
            title_text = "大佳新内容推送"
            bbox = draw.textbbox((0, 0), title_text, font=font_title)
            title_width = bbox[2] - bbox[0]
            draw.text(((img_width - title_width) // 2, y), title_text, 
                    fill=title_color, font=font_title)
            y += 50
            
            draw.line([40, y, img_width - 40, y], fill=border_color, width=2)
            y += 25
            
            # 绘制作者和时间
            draw.text((40, y), f" 作者: {author_name}", 
                    fill=info_color, font=font_info)
            y += 25
            draw.text((40, y), f" 时间: {create_time}", 
                    fill=info_color, font=font_info)
            y += 30
            
            # 在时间和内容之间添加分割线
            draw.line([40, y, img_width - 40, y], fill=border_color, width=1)
            y += 20
            
            # 绘制内容标签
            draw.text((40, y), " 内容:", fill=info_color, font=font_info)
            y += 25
            
            # 处理内容文本（自动换行）
            max_content_width = img_width - 80
            content_lines = []
            
            # 按换行符分割段落
            paragraphs = content.split('\n')
            for para in paragraphs:
                if para.strip():
                    # 逐字添加，计算实际宽度
                    current_line = ""
                    for char in para:
                        test_line = current_line + char
                        bbox = draw.textbbox((0, 0), test_line, font=font_text)
                        line_width = bbox[2] - bbox[0]
                        
                        if line_width <= max_content_width:
                            current_line = test_line
                        else:
                            # 当前行宽度超出，换到下一行
                            if current_line:
                                content_lines.append(current_line)
                            current_line = char
                    
                    # 添加最后一行
                    if current_line:
                        content_lines.append(current_line)
                else:
                    content_lines.append("")  # 保留空行
            
            # 绘制内容（限制行数，超出部分省略）
            max_lines = 35  # 最多显示35行
            for line in content_lines[:max_lines]:
                if line:
                    draw.text((40, y), line, fill=text_color, font=font_text, stroke_width=1, stroke_fill=(240, 240, 240))
                y += 40
            
            if len(content_lines) > max_lines:
                draw.text((40, y), "... (内容过长，已截断)", 
                        fill=info_color, font=font_info)
                y += 25
                
            # 添加旋转45度水印"六便士出品"（在最后一张图片位置，最上层）
            try:
                watermark_text = "六便士出品，欢迎联系作者微信：yughurt1984"
                watermark_font_size = 32
                
                # 尝试加载字体
                try:
                    watermark_font = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", watermark_font_size)
                except:
                    watermark_font = ImageFont.load_default()
                
                # 计算水印文字的尺寸
                temp_draw = ImageDraw.Draw(image)
                watermark_bbox = temp_draw.textbbox((0, 0), watermark_text, font=watermark_font)
                watermark_w = watermark_bbox[2] - watermark_bbox[0]
                watermark_h = watermark_bbox[3] - watermark_bbox[1]
                
                # 创建一个足够大的临时图片来容纳旋转后的水印
                diagonal = int((watermark_w ** 2 + watermark_h ** 2) ** 0.5) + 40
                watermark_img = Image.new('RGBA', (diagonal, diagonal), (255, 255, 255, 0))
                watermark_draw = ImageDraw.Draw(watermark_img)
                
                # 在临时图片中心绘制水印文字（调淡颜色）
                watermark_color = (180, 180, 180, 150)  # 浅灰色，透明度150
                text_x = (diagonal - watermark_w) // 2
                text_y = (diagonal - watermark_h) // 2
                watermark_draw.text((text_x, text_y), watermark_text, 
                                 fill=watermark_color, font=watermark_font)
                
                # 旋转45度
                watermark_img = watermark_img.rotate(45, expand=False)
                
                 # 计算水印位置：在内容结束位置的斜45°方向
                watermark_base_x = img_width // 2  # 水平居中
                watermark_base_y = y  # 内容结束位置的Y坐标
                
                # 水印位于基准位置的斜45°上方
                # 向右下45°方向偏移
                offset_x = 10   # 水平偏移（向右）
                offset_y = 0  # 垂直偏移（向上，负值表示向上）
                watermark_x = watermark_base_x - diagonal // 2 + offset_x
                watermark_y = watermark_base_y - diagonal // 2 + offset_y
                
                # 将水印粘贴到主图片上（最上层）
                image.paste(watermark_img, (watermark_x, watermark_y), watermark_img)
                
                self.log(f"   ✅ 已添加水印: {watermark_text} 位置({watermark_x}, {watermark_y})")
            except Exception as e:
                self.log(f"   ⚠️ 添加水印失败: {e}")
                import traceback
                self.log(f"   详细错误: {traceback.format_exc()}")    
            
            # 绘制底部信息
            y += 20
            draw.line([40, y, img_width - 40, y], fill=border_color, width=1)
            y += 25
            
            # ✅ 修改：删除"第几条"统计，只保留来源信息
            footer_text = f" 本内容由六便士整理推送,有需要请联系vx:yughurt1984"
            footer_bbox = draw.textbbox((0, 0), footer_text, font=font_info)
            footer_width = footer_bbox[2] - footer_bbox[0]
            draw.text(((img_width - footer_width) // 2, y), footer_text, 
                    fill=info_color, font=font_info)
            
            # 保存图片到临时目录
            temp_dir = os.path.join(os.path.dirname(__file__), "temp_images")
            os.makedirs(temp_dir, exist_ok=True)
            
            # 生成文件名（使用时间戳避免冲突）
            import time
            timestamp = int(time.time() * 1000)
            image_filename = f"text_msg_{timestamp}.png"
            image_path = os.path.join(temp_dir, image_filename)
            
            # 保存图片
            image.save(image_path, 'PNG', quality=95,dpi=(600, 600))
            
            self.log(f"   ✅ 文本已转换为图片: {image_path}")
            return image_path
            
        except Exception as e:
            self.log(f"   ❌ 文本转图片失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    
    def _handle_text_message(self, index: int, title: str, content: str, author_name: str, 
                       create_time: str, total: int) -> bool:
        """
        处理纯文本消息推送（分支4）
        修改：先将文本转换为图片，然后推送图片
        """
        try:
            # 清理HTML标签
            title = clean_html_tags(title)
            content = clean_html_tags(content)
            
            # ✅ 修改：将文本转换为图片
            image_path = self._text_to_image(
                title=title,
                content=content,
                author_name=author_name,
                create_time=create_time,
                index=index,
                total=total
            )
            
            if not image_path:
                self.log(f"❌ 第{index}/{total}条：文本转图片失败")
                return False
            
            # ✅ 修改：发送图片而不是markdown消息
            if self.send_image(image_path):
                self.log(f"✅ 第{index}/{total}条推送成功（图片）")
                
                # 清理临时图片文件
                try:
                    os.remove(image_path)
                    self.log(f"   🗑️ 已删除临时图片: {image_path}")
                except:
                    pass
                
                return True
            else:
                self.log(f"❌ 第{index}/{total}条推送失败")
                return False
            
        except Exception as e:
            self.log(f"❌ 第{index}条文本推送异常: {e}")
            import traceback
            traceback.print_exc()
            return False

