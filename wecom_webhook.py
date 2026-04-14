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
    
    # ========== 干扰功能配置 ==========
        # 需要启用干扰功能的群组ID列表（在此配置）
    NOISE_GROUPS = [
        # "your_group_id_1",  # 示例：替换为实际群组ID
        # "your_group_id_2",
        "28858542222551"
    ]
        
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
    
    def send_new_topics_notification(self, new_topics: List[Dict], stats: Dict, crawler=None) -> bool:
        """
        发送新话题推送通知
        
        Args:
            new_topics: 新话题列表
            stats: 统计信息
            crawler: 爬虫实例必需
        Returns:
            是否发送成功
        """
        if not self.enabled or not new_topics:
            return False
        
        # ✅ 限制最多推送10个话题-改为不限制话题数量
        topics_to_send = new_topics
        success_count = 0
        
        # 添加前10个新话题的预览，为每个话题单独推送
        for i, topic in enumerate(topics_to_send, 1):
            try:
                title = topic.get('title', '无标题')
                talk = topic.get('talk', {})

                # 获取内容（处理问答类型）
                question = topic.get('question', {})
                answer = topic.get('answer', {})

                question_image_urls = []  # 初始化

                # 判断是否是问答类型
                if question or answer:
                    # 问答类型：组合问题和回答
                    content_parts = []
                    
                    # 获取提问者信息
                    question_owner = question.get('owner', {})
                    question_name = question_owner.get('name', '匿名')
                    if question.get('anonymous', False):
                        question_name = '匿名用户'
                    
                    # 添加问题
                    question_text = question.get('text', '')
                    if question_text:
                        content_parts.append(f"【提问】{question_name}：\n{question_text}")
                    
                    # 获取回答者信息
                    answer_owner = answer.get('owner', {})
                    answer_name = answer_owner.get('name', '未知')
                    
                    # 添加回答
                    answer_text = answer.get('text', '')
                    if answer_text:
                        content_parts.append(f"【回答】{answer_name}：\n{answer_text}")
                    
                    content = '\n\n'.join(content_parts) if content_parts else '无内容'
                    
                    # 🆕 提取提问的图片URL
                    question_images = question.get('images', [])
                    for img in question_images:
                        url = img.get('large', {}).get('url') or img.get('thumbnail', {}).get('url')
                        if url:
                            question_image_urls.append(url)

                else:
                    # 普通话题：从talk获取内容
                    content = talk.get('text', '无内容')
                
                # 🆕 统一提取内容图片（包括talk和question）
                all_content_images = []
                
                # 从talk提取图片
                talk_images = self._extract_images(talk)
                all_content_images.extend(talk_images)
                
                # 🆕 同时从topic顶层提取图片（数据库增强数据格式）
                if not talk_images and 'images' in topic:
                    topic_images = topic.get('images', [])
                    for img in topic_images:
                        if isinstance(img, dict):
                            img_url = (img.get('original', {}).get('url') or
                                       img.get('large', {}).get('url') or
                                       img.get('thumbnail', {}).get('url'))
                            if img_url:
                                all_content_images.append(img_url)
                
                # 从question提取图片（问答类型）
                all_content_images.extend(question_image_urls)


                create_time = topic.get('create_time', '未知时间')
                
                # 作者信息：问答类型显示回答者，普通话题显示发布者
                if question or answer:
                    # 问答类型：优先显示回答者
                    if answer and answer.get('owner'):
                        author_name = answer.get('owner', {}).get('name', '未知')
                    elif question and question.get('owner') and not question.get('anonymous', False):
                        author_name = question.get('owner', {}).get('name', '匿名用户')
                    else:
                        author_name = '匿名用户'
                else:
                    # 普通话题：从talk获取
                    owner = talk.get('owner', {})
                    author_name = owner.get('name', '六便士')

                
                # 提取文章链接
                article_url = self._extract_article_url(talk, topic)
                
                # 提取附件列表
                topic_files = talk.get('files', [])
                '''
                分支1: 有zsxq链接 → _handle_article_pdf() → convert_url_to_pdf()
                分支2: 有附件 → _handle_attachments()
                分支3: 有图片 → convert_text_and_images_to_pdf() → _create_text_page()
                分支4: 纯文本 → convert_text_to_pdf() → _create_text_page()
                '''
                # ========== 2. 分支1: 有zsxq链接 → 只推送链接内容 ==========
                if article_url and 'zsxq' in article_url and crawler:
                    topic_id = topic.get('topic_id')
                    if self._handle_article_pdf(i, article_url, title, crawler, len(new_topics), topic_id, topic_files):
                        success_count += 1
                    continue  # 已处理，跳过后续分支

                
                # ========== 2. 分支2: 有附件 → 推送附件（含图片则一并推送） ==========
                if topic_files and crawler:
                    # 先下载附件
                    attachment_success = self._handle_attachments(i, topic_files, title, crawler, len(new_topics))
                    
                    # 如果同时有图片，也推送图片
                    if all_content_images:
                        self.log(f"   🖼️ 附件推送完成，继续处理{len(all_content_images)}张图片...")
                        pdf_output_dir = self._get_pdf_output_dir(crawler)
                        
                        # 下载图片
                        image_paths = []
                        for idx, img_url in enumerate(all_content_images, 1):
                            img_path = self._download_image(img_url, pdf_output_dir, idx)
                            if img_path:
                                image_paths.append(img_path)
                        
                        if image_paths:
                            # 创建图片PDF（使用 PyMuPDF）
                            timestamp = int(time.time() * 1000)
                            images_pdf = os.path.join(pdf_output_dir, f"images_{i}_{timestamp}.pdf")
                            if self._create_images_pdf_with_mupdf(image_paths, images_pdf):
                                if self.send_file(images_pdf):
                                    self.log(f"   ✅ 图片PDF推送成功")
                                else:
                                    self.log(f"   ⚠️ 图片PDF推送失败")
                            else:
                                self.log(f"   ❌ 图片PDF生成失败")
                    
                    if attachment_success:
                        success_count += 1
                    continue  # 已处理，跳过后续分支
                
                # ========== 3. 分支3: 有图片 → 整合文本和图片到PDF ==========
                # 注意：外部链接会当作文本出现在PDF中
                if all_content_images and crawler:
                    self.log(f"🖼️ 第{i}/{len(new_topics)}条：检测到{len(all_content_images)}张图片，合并为PDF...")
                    
                    pdf_output_dir = self._get_pdf_output_dir(crawler)
                    
                    pdf_path = self.convert_text_and_images_to_pdf(
                        title=title,
                        content=content,
                        author_name=author_name,
                        create_time=create_time,
                        index=i,
                        total=len(new_topics),
                        image_urls=all_content_images,
                        output_dir=pdf_output_dir,
                        group_id=crawler.group_id  # 新增
                    )
                    
                    if pdf_path:
                        if self.send_file(pdf_path):
                            self.log(f"✅ 第{i}/{len(new_topics)}条推送成功（PDF）")
                            success_count += 1
                        else:
                            self.log(f"❌ 第{i}/{len(new_topics)}条推送失败")
                    else:
                        self.log(f"❌ 第{i}/{len(new_topics)}条PDF生成失败")
                    
                    continue
                
                # ========== 4. 分支4: 纯文本推送 → 转PDF ==========
                pdf_output_dir = self._get_pdf_output_dir(crawler)
                pdf_path = self.convert_text_to_pdf(
                    title=title,
                    content=content,
                    author_name=author_name,
                    create_time=create_time,
                    index=i,
                    total=len(new_topics),
                    output_dir=pdf_output_dir,
                    group_id=crawler.group_id  # 新增

                )
                
                if pdf_path:
                    if self.send_file(pdf_path):
                        self.log(f"✅ 第{i}/{len(new_topics)}条推送成功（PDF）")
                        success_count += 1
                    else:
                        self.log(f"❌ 第{i}/{len(new_topics)}条PDF已存在，跳过推送")
                else:
                    self.log(f"❌ 第{i}/{len(new_topics)}条PDF生成失败")
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


    def convert_text_to_pdf(self, title: str, content: str, author_name: str,
                        create_time: str, index: int, total: int,
                        output_dir: str, group_id: str = None) -> Optional[str]:

        """
        将文本内容转换为PDF（分支4使用）
                
        Args:
            title: 标题
            content: 内容
            author_name: 作者名
            create_time: 创建时间
            index: 当前索引
            total: 总数
            output_dir: PDF输出目录
                
        Returns:
            PDF文件路径，失败返回None
        """
        try:
            # 清理HTML标签
            title = clean_html_tags(title)
            content = clean_html_tags(content)
            
            # 使用PIL绘制PDF
            pdf_path = self.convert_text_and_images_to_pdf(
                title=title,
                content=content,
                author_name=author_name,
                create_time=create_time,
                image_urls=[],  # 纯文本，无图片
                index=index,
                total=total,
                output_dir=output_dir,
                group_id=group_id
            )
            
            return pdf_path
            
        except Exception as e:
            self.log(f"   ❌ 文本转PDF失败: {e}")
            import traceback
            traceback.print_exc()
            return None


    def convert_text_and_images_to_pdf(self, title: str, content: str, author_name: str,
                                create_time: str, index: int, total: int,
                                image_urls: List[str], output_dir: str,
                                group_id: str = None) -> Optional[str]:

        """
        将文本内容和图片合并成一个PDF（分支3使用）
        
        """
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            # 下载图片
            image_paths = []
            self.log(f"   🖼️ 下载{len(image_urls)}张图片...")
            
            for i, img_url in enumerate(image_urls, 1):
                try:
                    img_path = self._download_image(img_url, output_dir, i)
                    if img_path:
                        image_paths.append(img_path)
                        self.log(f"   ✅ 图片{i}下载成功")
                except Exception as e:
                    self.log(f"   ⚠️ 图片{i}下载失败: {e}")
            
            # 绘制PDF
            pdf_path = self._text_and_images_to_pdf(
                title=title,
                content=content,
                author_name=author_name,
                create_time=create_time,
                image_paths=image_paths,
                index=index,
                total=total,
                output_dir=output_dir,
                group_id=group_id

            )
            
            return pdf_path
            
        except Exception as e:
            self.log(f"   ❌ PDF生成失败: {e}")
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
    
    def _handle_article_pdf(self, index: int, article_url: str, title: str, crawler, total: int, topic_id: int = None, topic_files: list = None) -> bool:
        """处理文章PDF推送（分支1）- 优先使用已生成的PDF"""
        try:
            # 🆕 优先检查 topic_files 中是否已有 PDF
            if topic_files:
                for file_info in topic_files:
                    local_path = file_info.get('local_path', '')
                    if local_path and local_path.endswith('.pdf') and os.path.exists(local_path):
                        self.log(f"📄 第{index}/{total}条：发现已生成的PDF，直接推送...")
                        if self.send_file(local_path):
                            self.log(f"   ✅ PDF推送成功")
                            return True
                        else:
                            self.log(f"   ⚠️ PDF推送失败，尝试重新生成")
                            break
            
            # 没有现成的 PDF，需要生成
            self.log(f"📄 第{index}/{total}条：检测到文章链接，开始转换PDF...")
            
            # 获取PDF输出目录
            pdf_output_dir = self._get_pdf_output_dir(crawler)
            
            # 调用自己的方法，传入cookie
            pdf_path = self.convert_url_to_pdf(
                article_url, 
                pdf_output_dir, 
                title,
                cookie=crawler.cookie
            )
            
            if pdf_path:
                # 添加背景和干扰
                temp_pdf_path = pdf_path.replace('.pdf', '_temp_with_bg.pdf')
                if self._add_background_and_noise_to_pdf(pdf_path, temp_pdf_path, group_id=crawler.group_id):
                    # 加密
                    self._encrypt_pdf(temp_pdf_path)
                    
                    # 重命名
                    final_path = pdf_path.replace('.pdf', '_作者微信MK0914666.pdf')
                    shutil.move(temp_pdf_path, final_path)
                    
                    # 删除原文件
                    try:
                        os.remove(pdf_path)
                    except:
                        pass
                    
                    pdf_path = final_path
                    self.log(f"   📋 已添加背景和干扰")
                else:
                    # 失败时仍然加密原文件
                    self._encrypt_pdf(pdf_path)
                
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
        """处理附件下载和推送（分支2）
        
        处理流程：
        1. 下载源文件
        2. 添加水印
        3. 加密
        4. 删除源文件，只保留处理后的文件
        5. 推送
        """
        try:
            self.log(f"📎 第{index}/{total}条：检测到附件（共{len(topic_files)}个）")
            
            # 获取文件下载器
            downloader = crawler.get_file_downloader()
            
            pushed_count = 0
            for file_info in topic_files:
                try:
                    # 构造file_info字典
                    file_data = {'file': file_info}
                    
                    # 获取文件名
                    file_name = file_info.get('name', 'Unknown')
                    # 清理文件名（保留中文）
                    safe_filename = "".join(c for c in file_name if c.isalnum() or c in '._-（）()[]{}' or '\u4e00' <= c <= '\u9fff')
                    if not safe_filename:
                        safe_filename = f"file_{file_info.get('id', 'unknown')}"
                    
                    # 源文件路径
                    source_path = os.path.join(downloader.download_dir, safe_filename)
                    
                    # 处理后的文件名（改名）
                    base_name = os.path.splitext(safe_filename)[0]
                    final_filename = f"{base_name}_作者微信MK0914666.pdf"
                    final_path = os.path.join(downloader.download_dir, final_filename)
                    
                    # ============ 检查最终文件是否已存在 ============
                    if os.path.exists(final_path):
                        self.log(f"   ✅ 已存在处理后的文件: {final_filename}")
                        # 直接推送
                        if self.send_file(final_path):
                            self.log(f"   ✅ 企业微信推送成功")
                            pushed_count += 1
                        else:
                            self.log(f"   ⚠️ 企业微信推送失败")
                        continue
                    
                    # ============ 下载源文件（如果不存在） ============
                    if not os.path.exists(source_path):
                        result = downloader.download_file(file_data)
                        if not result:
                            self.log(f"   ❌ 文件下载失败: {file_name}")
                            continue
                        if result == "skipped":
                            self.log(f"   ⏭️ 文件已存在但未处理: {safe_filename}")
                    
                    # 确认源文件存在
                    if not os.path.exists(source_path):
                        self.log(f"   ❌ 源文件不存在: {source_path}")
                        continue
                    
                    # ============ 处理PDF文件 ============
                    if source_path.lower().endswith('.pdf'):
                        self.log(f"   🖼️ 处理PDF: {safe_filename}")
                        
                        # 步骤1: 添加背景和水印
                        temp_processed = source_path.replace('.pdf', '_temp_processed.pdf')
                        if not self._add_background_and_noise_to_pdf(source_path, temp_processed, group_id=crawler.group_id if crawler else None):
                            self.log(f"   ⚠️ 处理失败，使用源文件")
                            temp_processed = source_path
                        
                        # 步骤2: 加密
                        self._encrypt_pdf(temp_processed)
                        
                        # 步骤3: 重命名
                        shutil.move(temp_processed, final_path)
                        
                        # 步骤4: 删除源文件
                        if source_path != temp_processed:
                            try:
                                os.remove(source_path)
                                self.log(f"   🗑️ 已删除源文件: {safe_filename}")
                            except:
                                pass
                        
                        self.log(f"   ✅ 处理完成: {final_filename}")
                        
                        # 步骤5: 推送
                        if self.send_file(final_path):
                            self.log(f"   ✅ 企业微信推送成功")
                            pushed_count += 1
                        else:
                            self.log(f"   ⚠️ 企业微信推送失败")

                            
                    else:
                        # 非PDF文件，直接发送
                        self.log(f"   📱 正在推送: {safe_filename}")
                        if self.send_file(source_path):
                            self.log(f"   ✅ 企业微信推送成功")
                            pushed_count += 1
                        else:
                            self.log(f"   ⚠️ 企业微信推送失败")
                            
                except Exception as e:
                    self.log(f"   ❌ 附件处理异常: {e}")
                    import traceback
                    traceback.print_exc()
            
            if pushed_count > 0:
                self.log(f"   ✅ 附件处理完成：推送{pushed_count}个")
                return True
            else:
                self.log(f"   ⚠️ 所有附件推送失败")
                return False
                
        except Exception as e:
            self.log(f"   ❌ 附件处理异常: {e}")
            import traceback
            traceback.print_exc()
            return False

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
            
            enable_noise = group_id in self.NOISE_GROUPS if group_id else False
            
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
                if enable_noise:
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
                    # 尝试多个可能的URL字段
                    img_url = (img.get('original', {}).get('url') or
                               img.get('large', {}).get('url') or
                               img.get('thumbnail', {}).get('url'))
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

    def _calculate_text_lines(self, content: str, max_width: float, fontsize: int = 18,
                          font_path: str = None, font_name: str = None) -> list:
        """计算文字行（自动换行），使用字符宽度估算"""
        lines = []
        current_line = ""
        
        for char in content:
            if char == '\n':
                if current_line:
                    lines.append(current_line)
                    current_line = ""
                lines.append(None)  # 空行标记
                continue
            
            test_line = current_line + char
            
            # 计算文字宽度（估算方法）
            # 中文字符约等于 fontsize 宽度，英文约等于 fontsize * 0.5
            text_width = 0
            for c in test_line:
                if '\u4e00' <= c <= '\u9fff':
                    text_width += fontsize * 1.0  # 中文字符
                elif c.isalpha() or c.isdigit():
                    text_width += fontsize * 0.5  # 英文/数字
                else:
                    text_width += fontsize * 0.6  # 其他字符（标点等）
            
            if text_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char
        
        if current_line:
            lines.append(current_line)
        
        return lines

    def _text_and_images_to_pdf(self, title: str, content: str, author_name: str, 
                            create_time: str, image_paths: List[str], 
                            index: int, total: int, output_dir: str,
                            group_id: str = None) -> Optional[str]:
        """
        将文本内容和图片生成PDF（使用 PIL 渲染）
        """
        try:
            # 清理HTML标签
            title = clean_html_tags(title)
            content = clean_html_tags(content)
            
            # 使用 PIL 渲染
            pdf_path = self._create_pdf_with_pil(
                title=title,
                content=content,
                author_name=author_name,
                create_time=create_time,
                image_paths=image_paths,
                output_dir=output_dir,
                group_id=group_id
            )
            
            return pdf_path
            
        except Exception as e:
            self.log(f"   ❌ PDF生成失败: {e}")
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
        
    def _create_images_pdf_with_mupdf(self, image_paths: List[str], output_path: str,
                                   background_image_path: str = None) -> bool:
        """使用 PyMuPDF 创建图片PDF"""
        try:
            doc = fitz.open()
            
            page_width = 794
            page_height = 1123
            page_padding = 40
            title_height = 80
            
            font_path = r"C:\Windows\Fonts\simhei.ttf"
            font_name = "simhei"
            
            total_images = len(image_paths)
            
            for i, img_path in enumerate(image_paths):
                page = doc.new_page(width=page_width, height=page_height)
                
                # 插入背景图片（如有）
                if background_image_path and os.path.exists(background_image_path):
                    bg_rect = fitz.Rect(0, 0, page_width, page_height)
                    page.insert_image(bg_rect, filename=background_image_path)
                
                # 绘制标题
                title_text = f"附件图片 ({i+1}/{total_images})"
                page.insert_text(
                    fitz.Point(page_padding, 50),
                    title_text,
                    fontfile=font_path,
                    fontname=font_name,
                    fontsize=20,
                    color=(0, 0, 0)
                )
                
                # 绘制分隔线
                page.draw_line(
                    fitz.Point(page_padding, 70),
                    fitz.Point(page_width - page_padding, 70),
                    color=(0.78, 0.78, 0.78),
                    width=1
                )
                
                # 获取图片实际尺寸
                img_doc = fitz.open(img_path)
                img_page = img_doc[0]
                img_w = img_page.rect.width
                img_h = img_page.rect.height
                img_doc.close()
                
                # 最大可用区域（调整边距）
                max_width = page_width - page_padding * 2
                max_height = page_height - title_height - page_padding * 2
                
                # 计算缩放比例
                ratio_w = max_width / img_w
                ratio_h = max_height / img_h
                ratio = min(ratio_w, ratio_h, 1)
                
                new_w = img_w * ratio
                new_h = img_h * ratio
                
                # 计算居中位置
                x = (page_width - new_w) / 2
                y = title_height + page_padding
                
                # 插入图片
                img_rect = fitz.Rect(x, y, x + new_w, y + new_h)
                page.insert_image(img_rect, filename=img_path)
                
                self.log(f"   ✅ 图片{i+1}处理成功 ({img_w:.0f}x{img_h:.0f} -> {new_w:.0f}x{new_h:.0f})")
            
            # 保存（压缩）
            doc.save(output_path, deflate=True, garbage=3)
            doc.close()
            
            self.log(f"   📄 生成 {total_images} 页图片PDF")
            return True
            
        except Exception as e:
            self.log(f"   ❌ 图片PDF生成失败: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def _create_pdf_with_pil(self, title: str, content: str, author_name: str,
                            create_time: str, image_paths: List[str],
                            output_dir: str, group_id: str = None) -> Optional[str]:
        """
        使用 PIL 渲染文本到背景图，生成带干扰功能的 PDF
        
        Args:
            title: 标题
            content: 内容
            author_name: 作者名
            create_time: 创建时间
            image_paths: 图片路径列表
            output_dir: 输出目录
            group_id: 群组ID（用于判断是否启用干扰）
            
        Returns:
            PDF文件路径，失败返回None
        """
        try:
            # ============ 路径配置 ============
            bg_path = os.path.join(os.path.dirname(__file__), "images", "pdf_background.png")
            temp_dir = os.path.join(os.path.dirname(__file__), "temp_pdf_pages")
            os.makedirs(temp_dir, exist_ok=True)
            
            # ============ 页面参数 ============
            img_width = 794
            img_height = 1123
            footer_reserved = 140
            editable_height = img_height - footer_reserved
            
            # ============ 字体配置 ============
            default_font_path = r"C:\Windows\Fonts\msyh.ttc"
            
            # 干扰字体列表
            noise_fonts = [
                r"C:\Windows\Fonts\miaobihuiyinti_0.ttf",
                r"C:\Windows\Fonts\miaobishuobingti.ttf",
            ]
            
            try:
                font_title = ImageFont.truetype(default_font_path, 32)
                font_text = ImageFont.truetype(default_font_path, 22)
                font_info = ImageFont.truetype(default_font_path, 16)
                font_noise_text = ImageFont.truetype(default_font_path, 16)  # 干扰文字小字号
            except Exception as e:
                self.log(f"   ❌ 字体加载失败: {e}")
                return None

            # 选择干扰字体（只用于随机更换字体）
            selected_noise_font = random.choice(noise_fonts)
            try:
                font_noise = ImageFont.truetype(selected_noise_font, 22)
            except Exception as e:
                self.log(f"   ⚠️ 干扰字体加载失败: {e}")
                font_noise = font_text
            
            # ============ 判断是否启用干扰功能 ============
            enable_noise = group_id in self.NOISE_GROUPS if group_id else False
            
            # ============ 干扰文字内容 ============
            noise_text = "（原作者微信：MK0914666）"
            
            # ============ 处理内容 ============
            if enable_noise:
                marked_content = self._process_content_with_noise(content, noise_text, min_noise_chars=100)
                self.log(f"   🔧 已启用干扰功能（群组: {group_id}）")
            else:
                # 不启用干扰，全部使用正常字体（类型0）
                marked_content = [(char, 0) for char in content]
            
            # ============ 加载背景图片 ============
            def load_background():
                if os.path.exists(bg_path):
                    img = Image.open(bg_path)
                    img = img.resize((img_width, img_height), Image.Resampling.LANCZOS)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    return img
                return Image.new('RGB', (img_width, img_height), (255, 255, 255))
            
            # ============ 自动换行处理 ============
            max_content_width = img_width - 80
            
            temp_img = Image.new('RGB', (1, 1))
            temp_draw = ImageDraw.Draw(temp_img)
            
            content_lines = []
            current_line = []
            current_width = 0
            
            for char, font_type in marked_content:
                if char == '\n':
                    if current_line:
                        content_lines.append(current_line)
                        content_lines.append([])  # 只在段落结束后添加一个空行
                    current_line = []
                    current_width = 0
                    continue
                
                font = font_noise if font_type == 1 else (font_noise_text if font_type == 2 else font_text)
                bbox = temp_draw.textbbox((0, 0), char, font=font)
                char_width = bbox[2] - bbox[0]
                
                if current_width + char_width <= max_content_width:
                    current_line.append((char, font_type))
                    current_width += char_width
                else:
                    if current_line:
                        content_lines.append(current_line)
                    current_line = [(char, font_type)]
                    current_width = char_width
            
            if current_line:
                content_lines.append(current_line)
            
            # ============ 创建页面辅助函数 ============
            def create_new_page(is_first_page):
                page = load_background()
                draw = ImageDraw.Draw(page)
                y = 40
                
                if is_first_page:
                    draw.rectangle([30, y, img_width - 30, y + 3], fill=(200, 200, 200))
                    y += 20
                    
                    bbox = draw.textbbox((0, 0), "新内容推送", font=font_title)
                    title_w = bbox[2] - bbox[0]
                    draw.text(((img_width - title_w) // 2, y), "新内容推送", fill=(0, 0, 0), font=font_title)
                    y += 50
                    
                    draw.line([30, y, img_width - 30, y], fill=(200, 200, 200), width=2)
                    y += 25
                    
                    draw.text((30, y), f" 作者: {author_name}", fill=(100, 100, 100), font=font_info)
                    y += 25
                    draw.text((30, y), f" 时间: {create_time}", fill=(100, 100, 100), font=font_info)
                    y += 35
                    
                    draw.line([30, y, img_width - 30, y], fill=(200, 200, 200), width=1)
                    y += 25
                    
                    draw.text((30, y), "【内容】:", fill=(70, 70, 70), font=font_text)
                    y += 30
                else:
                    draw.text((30, y), "新内容推送 (续)", fill=(70, 70, 70), font=font_info)
                    y += 25
                    draw.line([30, y, img_width - 30, y], fill=(200, 200, 200), width=1)
                    y += 20
                
                return page, draw, y
            
            # ============ 多页渲染（带行间干扰文字） ============
            pages = []
            current_page, current_draw, y = create_new_page(is_first_page=True)
            pages.append(current_page)
            
            text_color = (70, 70, 70)
            noise_color = (50, 100, 200)  # 蓝色
            
            for line_chars in content_lines:
                if y + 28 > editable_height:
                    current_page, current_draw, y = create_new_page(is_first_page=False)
                    pages.append(current_page)
                
                # 渲染正文行
                x = 40
                for char, font_type in line_chars:
                    if font_type == 0:
                        font = font_text
                        color = text_color
                    elif font_type == 1:
                        font = font_noise
                        color = text_color
                    else:  # font_type == 2
                        font = font_noise_text
                        color = noise_color
                    
                    current_draw.text((x, y), char, fill=color, font=font)
                    bbox = current_draw.textbbox((x, y), char, font=font)
                    x = bbox[2]
                
                y += 28
            
            # ============ 保存临时图片 ============
            timestamp = int(time.time() * 1000)
            temp_images = []
            for i, page in enumerate(pages):
                temp_path = os.path.join(temp_dir, f"page_{timestamp}_{i}.png")
                page.save(temp_path)
                temp_images.append(temp_path)
            

            # ============ 图片转PDF ============
            temp_pdf = os.path.join(temp_dir, f"temp_{timestamp}.pdf")
            
            doc = fitz.open()
            for img_path in temp_images:
                page = doc.new_page(width=img_width, height=img_height)
                rect = fitz.Rect(0, 0, img_width, img_height)
                page.insert_image(rect, filename=img_path)
            doc.save(temp_pdf)
            doc.close()
            
            # ============ 处理图片（如有） ============
            if image_paths:
                doc = fitz.open(temp_pdf)
                for img_path in image_paths:
                    page = doc.new_page(width=img_width, height=img_height)
                    rect = fitz.Rect(30, 30, img_width - 30, img_height - 30)
                    page.insert_image(rect, filename=img_path)
                
                # 保存到不同的文件名（避免 save to original 错误）
                temp_pdf_with_images = os.path.join(temp_dir, f"temp_with_images_{timestamp}.pdf")
                doc.save(temp_pdf_with_images)
                doc.close()
                
                # 删除原临时文件，使用新文件
                try:
                    os.remove(temp_pdf)
                except:
                    pass
                temp_pdf = temp_pdf_with_images
            
            # ============ 加密PDF ============
            encrypted_pdf = os.path.join(temp_dir, f"encrypted_{timestamp}.pdf")
            
            doc = fitz.open(temp_pdf)
            owner_password = "protect_pdf@Arron"
            perm = 0
            
            doc.save(
                encrypted_pdf,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw=owner_password,
                user_pw="",
                permissions=perm
            )
            doc.close()
            
            # ============ 移动到最终位置 ============
            safe_author = re.sub(r'[^\w\u4e00-\u9fff]', '', author_name)
            time_str = time.strftime("%Y%m%d_%H%M%S")
            pdf_filename = f"{safe_author}_新内容推送_{time_str}_作者微信MK0914666.pdf"
            output_path = os.path.join(output_dir, pdf_filename)
            
            shutil.move(encrypted_pdf, output_path)
            
            # 清理临时文件
            for temp_path in temp_images:
                try:
                    os.remove(temp_path)
                except:
                    pass
            try:
                os.remove(temp_pdf)
            except:
                pass
            
            file_size = os.path.getsize(output_path) / 1024
            self.log(f"   ✅ PDF生成成功: {pdf_filename} ({len(pages)}页, {file_size:.1f}KB)")
            return output_path
            
        except Exception as e:
            self.log(f"   ❌ PDF生成失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _process_content_with_noise(self, content: str, noise_text: str, min_noise_chars: int = 100):
        """
        处理内容：先随机选择字体更换位置，再插入干扰文字
        
        Args:
            content: 原始内容
            noise_text: 干扰文字
            min_noise_chars: 最少更换字体的字符数
            
        Returns:
            [(char, font_type), ...] 列表
            font_type: 0=正常, 1=干扰字体, 2=干扰文字
        """
        chars = list(content)
        total_len = len(chars)
        
        # 步骤1：先随机选择要更换字体的位置
        normal_indices = [i for i, char in enumerate(chars) if char != '\n']
        
        selected_indices = set()
        if len(normal_indices) > min_noise_chars:
            noise_char_count = random.randint(min_noise_chars, min(min_noise_chars + 30, len(normal_indices)))
            selected_indices = set(random.sample(normal_indices, noise_char_count))
        
        marked_content = []
        for i, char in enumerate(chars):
            font_type = 1 if i in selected_indices else 0
            marked_content.append((char, font_type))
        
        # 步骤2：插入干扰文字（固定3次，随机位置）
        insert_times = 3
        
        insert_positions = []
        if total_len > 100:
            available_positions = list(range(30, total_len - 30))
            insert_positions = sorted(random.sample(available_positions, insert_times), reverse=True)
        
        for pos in insert_positions:
            noise_chars = [(char, 2) for char in noise_text]  # 类型2=干扰文字
            marked_content[pos:pos] = noise_chars
        
        self.log(f"   🎲 随机更换字体: {len(selected_indices)} 个字，插入干扰文字: {len(insert_positions)} 次")
        
        return marked_content

    