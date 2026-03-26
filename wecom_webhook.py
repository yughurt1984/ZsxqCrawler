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
from PyPDF2 import PdfReader, PdfWriter,PdfMerger
import traceback
import hashlib
from PIL import Image, ImageDraw, ImageFont  # ✅ 添加PIL导入
import random
import time
from datetime import datetime
import platform

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
                
                # ========== 2. 分支1: 有zsxq链接 → 只推送链接内容 ==========
                if article_url and 'zsxq' in article_url and crawler:
                    if self._handle_article_pdf(i, article_url, title, crawler, len(new_topics)):
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
                            # 创建图片PDF
                            images_pdf = self._create_images_pages(image_paths, pdf_output_dir)
                            if images_pdf:
                                # 添加水印模板
                                final_pdf = os.path.join(pdf_output_dir, f"images_{i}_{datetime.now().strftime('%H%M%S')}.pdf")
                                if self._merge_with_template(images_pdf, final_pdf):
                                    if self.send_file(final_pdf):
                                        self.log(f"   ✅ 图片PDF推送成功")
                                    else:
                                        self.log(f"   ⚠️ 图片PDF推送失败")
                    
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
                        output_dir=pdf_output_dir
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
                    output_dir=pdf_output_dir
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
                pdf_filename = f"{safe_title}_添加作者微信MK0914666.pdf"
            else:
                file_hash = hashlib.md5(url.encode()).hexdigest()[:12]
                pdf_filename = f"article_{file_hash}_添加作者微信MK0914666.pdf"
            
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
                            output_dir: str) -> Optional[str]:
        """
        将文本内容转换为PDF（分支4使用）
        使用PIL绘制，保留原有样式
        
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
                output_dir=output_dir
            )
            
            return pdf_path
            
        except Exception as e:
            self.log(f"   ❌ 文本转PDF失败: {e}")
            import traceback
            traceback.print_exc()
            return None


    def convert_text_and_images_to_pdf(self, title: str, content: str, author_name: str,
                                    create_time: str, index: int, total: int,
                                    image_urls: List[str], output_dir: str) -> Optional[str]:
        """
        将文本内容和图片合并成一个PDF（分支3使用）
        使用PIL绘制，保留原有样式
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
            
            # 使用PIL绘制PDF
            pdf_path = self._text_and_images_to_pdf(
                title=title,
                content=content,
                author_name=author_name,
                create_time=create_time,
                image_paths=image_paths,
                index=index,
                total=total,
                output_dir=output_dir
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
    
    def _handle_article_pdf(self, index: int, article_url: str, title: str, crawler, total: int) -> bool:
        """处理文章PDF转换和推送（分支1）"""
        try:
            self.log(f"📄 第{index}/{total}条：检测到文章链接，开始转换PDF...")
            
            # 获取PDF输出目录
            pdf_output_dir = self._get_pdf_output_dir(crawler)
            
            # 调用自己的方法，传入cookie
            pdf_path = self.convert_url_to_pdf(
                article_url, 
                pdf_output_dir, 
                title,
                cookie=crawler.cookie  # ✅ 传入知识星球Cookie
            )
            
            if pdf_path:
                # ⭐ 添加水印模板（用临时文件作为中间输出，然后覆盖原文件）
                temp_pdf_path = pdf_path.replace('.pdf', '_temp.pdf')
                if self._merge_with_template(pdf_path, temp_pdf_path):
                    # 用临时文件覆盖原文件
                    import shutil
                    shutil.move(temp_pdf_path, pdf_path)
                    self.log(f"   📋 已添加水印模板")
                    # 发送带水印的PDF
                    if self.send_file(pdf_path):
                        self.log(f"   ✅ PDF发送成功")
                        return True
                    else:
                        self.log(f"   ⚠️ PDF发送失败")
                else:
                    # 水印添加失败，直接发送原始PDF
                    self.log(f"   ⚠️ 水印添加失败，发送原始PDF")
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
                                # ⭐ 实际添加水印
                                watermarked_path = file_path.replace('.pdf', '_添加作者微信MK0914666.pdf')
                                if self._merge_with_template(file_path, watermarked_path):
                                    self.log(f"   ✅ 水印添加成功")
                                    # 发送带水印的PDF
                                    if self.send_file(watermarked_path):
                                        self.log(f"   ✅ 企业微信推送成功")
                                        pushed_count += 1
                                    else:
                                        self.log(f"   ⚠️ 企业微信推送失败")
                                    # 清理临时文件
                                    try:
                                        os.remove(watermarked_path)
                                    except:
                                        pass
                                else:
                                    # 水印添加失败，发送原始文件
                                    self.log(f"   ⚠️ 水印添加失败，发送原始文件")
                                    if self.send_file(file_path):
                                        self.log(f"   ✅ 企业微信推送成功")
                                        pushed_count += 1
                                    else:
                                        self.log(f"   ⚠️ 企业微信推送失败")
                            else:
                                # 非PDF文件，直接发送
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

    
    
    def _merge_with_template(self, content_pdf_path: str, output_path: str) -> bool:
        """
        将模板作为水印叠加到内容PDF上
        
        Args:
            content_pdf_path: 内容PDF路径
            output_path: 输出PDF路径
            
        Returns:
            是否成功
        """
        # 模板PDF路径
        TEMPLATE_PDF_PATH = os.path.join(os.path.dirname(__file__), "watermark.pdf")

        try:
            if not os.path.exists(TEMPLATE_PDF_PATH):
                self.log(f"   ⚠️ 模板文件不存在，跳过合并: {TEMPLATE_PDF_PATH}")
                return False
            
            # 读取模板（水印）
            watermark_reader = PdfReader(TEMPLATE_PDF_PATH)
            # 读取内容
            content_reader = PdfReader(content_pdf_path)
            
            writer = PdfWriter()
            
            for i, content_page in enumerate(content_reader.pages):
                # 获取内容页的实际尺寸
                content_width = content_page.mediabox.width
                content_height = content_page.mediabox.height
                
                # 获取水印页（循环使用）
                watermark_page = watermark_reader.pages[i % len(watermark_reader.pages)]
                
                # 获取水印页的尺寸
                watermark_width = watermark_page.mediabox.width
                watermark_height = watermark_page.mediabox.height
                
                # 计算缩放比例（水印适配内容页尺寸）
                from PyPDF2 import Transformation
                
                scale_x = float(content_width) / float(watermark_width)
                scale_y = float(content_height) / float(watermark_height)
                scale = min(scale_x, scale_y)  # 保持比例
                
                # 缩放水印页
                watermark_page.scale(scale, scale)
                
                # 将水印叠加到内容页上
                content_page.merge_page(watermark_page)
                writer.add_page(content_page)
            
            with open(output_path, 'wb') as f:
                writer.write(f)
            
            self.log(f"   📋 已添加水印模板")
            return True
            
        except Exception as e:
            self.log(f"   ❌ 水印添加失败: {e}")
            import traceback
            traceback.print_exc()
            return False


    def _text_and_images_to_pdf(self, title: str, content: str, author_name: str, 
                                create_time: str, image_paths: List[str], 
                                index: int, total: int, output_dir: str) -> Optional[str]:
        """
        将文本内容和图片绘制成PDF（使用PIL绘制，保留样式）
        第一页：文本内容
        第二页：图片（如有）
        
        Args:
            title: 标题
            content: 内容
            author_name: 作者名
            create_time: 创建时间
            image_paths: 图片路径列表
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
            
            # ============ 第一页：文本内容 ============
            text_page = self._create_text_page(title, content, author_name, create_time, index, total)
            
            # ============ 第二页：图片 ============
            pdf_pages = []

            # 临时文件目录（单独存放）
            temp_dir = os.path.join(os.path.dirname(__file__), "temp_pdf_pages")
            os.makedirs(temp_dir, exist_ok=True)
            
            # 保存文本页为临时文件
            timestamp = int(time.time() * 1000)
            temp_text_path = os.path.join(temp_dir, f"_temp_text_{timestamp}.png")
            text_page.save(temp_text_path)
            pdf_pages.append(temp_text_path)
            
            # 处理图片页
            if image_paths:
                images_pages = self._create_images_pages(image_paths)
                for i, page in enumerate(images_pages):
                    temp_images_path = os.path.join(output_dir, f"_temp_images_{timestamp}_{i}.png")
                    page.save(temp_images_path,quality=95, optimize=False)
                    pdf_pages.append(temp_images_path)
                
            # ============ 合并为PDF ============
             # 统一命名规则：作者_新内容推送_时间.pdf
            safe_author = re.sub(r'[^\w\u4e00-\u9fff]', '', author_name)
            time_str = time.strftime("%Y%m%d_%H%M%S")
            pdf_filename = f"{safe_author}_新内容推送_{time_str}.pdf"
            
            pdf_path = os.path.join(output_dir, pdf_filename)
            
            # 检查文件是否存在
            if os.path.exists(pdf_path):
                self.log(f"   ⏭️ PDF已存在，跳过: {pdf_filename}")
                # 清理临时文件
                for temp_path in pdf_pages:
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                return None
            
             # 多页合并保存为临时PDF
            temp_pdf_path = os.path.join(temp_dir, f"_temp_content_{timestamp}.pdf")
            first_image = Image.open(pdf_pages[0])
            other_images = [Image.open(p) for p in pdf_pages[1:]]
            first_image.save(temp_pdf_path, 'PDF', save_all=True, append_images=other_images, dpi=(300, 300))
            
            # 清理临时文件
            for temp_path in pdf_pages:
                try:
                    os.remove(temp_path)
                except:
                    pass
            
             # 与模板合并
            if self._merge_with_template(temp_pdf_path, pdf_path):
                self.log(f"   ✅ PDF生成成功（已合并模板）: {pdf_path} (共{len(pdf_pages)}页)")
                # 清理临时PDF
                try:
                    os.remove(temp_pdf_path)
                except:
                    pass
            else:
                # 模板合并失败，直接移动临时PDF
                import shutil
                shutil.move(temp_pdf_path, pdf_path)
                self.log(f"   ✅ PDF生成成功（无模板）: {pdf_path} (共{len(pdf_pages)}页)")
            
            return pdf_path
            
        except Exception as e:
            self.log(f"   ❌ 文本和图片合并失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _create_text_page(self, title: str, content: str, author_name: str, 
                          create_time: str, index: int, total: int) -> Image.Image:
        """
        创建文本页面（A4尺寸，底部预留120px）
        
        Returns:
            PIL Image对象
        """
        # A4尺寸 (像素)
        img_width = 794
        img_height = 1123
        footer_reserved = 120  # 底部预留高度
        editable_height = img_height - footer_reserved  # 可编辑区域高度
        
        background_color = (255, 255, 255)
        temp_image = Image.new('RGB', (img_width, 100), background_color)
        temp_draw = ImageDraw.Draw(temp_image)
        
        # 尝试加载字体（增加对服务器字体的支持）
        system = platform.system()

        if system == "Windows":
            font_paths = [
                "C:\\Windows\\Fonts\\simhei.ttf",
                "C:\\Windows\\Fonts\\msyh.ttc",
                "C:\\Windows\\Fonts\\simsun.ttc",
                None
            ]
        else:  # Linux
            font_paths = [
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                None
            ]
        
        font_title = None
        font_text = None
        font_info = None
        
        for font_path in font_paths:
            try:
                if font_path:
                    font_title = ImageFont.truetype(font_path, 32)
                    font_text = ImageFont.truetype(font_path, 22)
                    font_info = ImageFont.truetype(font_path, 16)
                    break
            except:
                continue
        
        if font_title is None:
            font_title = ImageFont.load_default()
            font_text = ImageFont.load_default()
            font_info = ImageFont.load_default()
        
        # 计算文字行数
        max_content_width = img_width - 60
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
        
        # 创建A4尺寸图片
        image = Image.new('RGB', (img_width, img_height), background_color)
        draw = ImageDraw.Draw(image)
        
        # 颜色定义
        title_color = (0, 0, 0)
        text_color = (70, 70, 70)
        info_color = (100, 100, 100)
        border_color = (200, 200, 200)
        
        y = 40
        
        # 绘制顶部横线
        draw.rectangle([30, y, img_width - 30, y + 3], fill=border_color)
        y += 20
        
        # 绘制标题
        title_text = "新内容推送"
        bbox = draw.textbbox((0, 0), title_text, font=font_title)
        title_width = bbox[2] - bbox[0]
        draw.text(((img_width - title_width) // 2, y), title_text, 
                fill=title_color, font=font_title)
        y += 50
        
        # 绘制分隔线
        draw.line([30, y, img_width - 30, y], fill=border_color, width=2)
        y += 25
        
        # 绘制作者和时间
        draw.text((30, y), f" 作者: {author_name}", 
                fill=info_color, font=font_info)            
        y += 25
        draw.text((30, y), f" 时间: {create_time}", 
                fill=info_color, font=font_info)
        y += 35
        
        # 分割线
        draw.line([30, y, img_width - 30, y], fill=border_color, width=1)
        y += 25
        
        # 绘制内容标签
        draw.text((30, y), "【内容】:", fill=text_color, font=font_text)
        y += 30
        
        # 绘制内容（确保不超出可编辑区域）
        for line in content_lines:
            if y + 28 > editable_height:  # 超出可编辑区域，停止绘制
                break
            if line:
                # ⭐ 新增：检查行宽度，超长则截断
                bbox = draw.textbbox((0, 0), line, font=font_text)
                line_width = bbox[2] - bbox[0]
                
                if line_width > max_content_width:
                    # 强制截断到最大宽度
                    truncated_line = ""
                    for char in line:
                        test_line = truncated_line + char
                        test_bbox = draw.textbbox((0, 0), test_line, font=font_text)
                        if test_bbox[2] - test_bbox[0] > max_content_width:
                            break
                        truncated_line = test_line
                    line = truncated_line
                draw.text((40, y), line, fill=text_color, font=font_text)
                y += 28
        
        # 不绘制底部信息（由模板提供）
        return image
    
    def _create_images_pages(self, image_paths: List[str]) -> List[Image.Image]:
        """
        创建图片页面列表（A4尺寸，每行1张图片，保持原始比例，支持多页）
        
        Args:
            image_paths: 图片路径列表
            
        Returns:
            PIL Image对象列表（每个元素是一页）
        """
         # A4尺寸 (像素)
        page_width = 794
        page_height = 1123
        footer_reserved = 120  # 底部预留高度
        page_padding = 30
        title_height = 80
        
         # 图片最大宽度（不超过A4宽度）
        max_img_width = page_width - page_padding * 2
        # 图片最大高度（可编辑区域 - 标题区域）
        max_img_height = page_height - footer_reserved - title_height - page_padding * 2
        
        # 尝试加载字体
        try:
            if platform.system() == "Windows":
                font_title = ImageFont.truetype("C:\\Windows\\Fonts\\simhei.ttf", 24)
            else:
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 24)
        except:
            font_title = ImageFont.load_default()
        
        pages = []
        total_images = len(image_paths)
        
        for i, img_path in enumerate(image_paths):
            try:
                img = Image.open(img_path)
                img_w, img_h = img.size
                
                # 计算缩放比例，适应A4宽度（保持原始宽高比）
                ratio_w = max_img_width / img_w
                ratio_h = max_img_height / img_h
                ratio = min(ratio_w, ratio_h)
                
                # 如果图片比可用区域小，不放大
                if ratio > 1:
                    ratio = 1
                
                new_w = int(img_w * ratio)
                new_h = int(img_h * ratio)
                
                img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
                # 创建A4尺寸页面（白色背景，与模板合并后显示模板背景）
                page = Image.new('RGB', (page_width, page_height), (255, 255, 255))
                draw = ImageDraw.Draw(page)
                
                # 绘制标题
                title_text = f"附件图片 ({i+1}/{total_images})"
                draw.text((page_padding, page_padding), title_text, fill=(0, 0, 0), font=font_title)
                
                # 绘制分隔线
                y = page_padding + 40
                draw.line([page_padding, y, page_width - page_padding, y], fill=(200, 200, 200), width=1)
                y += 20
                
                 # 图片水平居中，紧跟分隔线下方
                x = (page_width - new_w) // 2
                paste_y = y + 5 # 横线下方留25px间距，不垂直居中
                
                # 粘贴图片
                page.paste(img_resized, (x, paste_y))
                
                pages.append(page)
                self.log(f"   ✅ 图片{i+1}处理成功 (原始:{img_w}x{img_h} -> 缩放:{new_w}x{new_h})")
                
            except Exception as e:
                self.log(f"   ❌ 图片{i+1}处理失败: {e}")
        
        if not pages:
            return [Image.new('RGB', (page_width, page_height), (255, 255, 255))]
        
        self.log(f"   📄 生成 {len(pages)} 页图片PDF")
        return pages

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
                   create_time: str, index: int, total: int,
                   question_images: Optional[List[str]] = None,
                   crawler = None) -> Optional[str]:
        """
        将文本内容转换为图片，支持嵌入图片
        
        Args:
            title: 标题
            content: 内容
            author_name: 作者名
            create_time: 创建时间
            index: 当前索引
            total: 总数
            images: 图片URL列表（可选）
            crawler: 爬虫实例，用于下载图片（可选）
                
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
            
            # 字体大小变量（可根据内容长度动态调整）
            base_font_size_title = 32
            base_font_size_text = 22
            base_font_size_info = 16
            
            for font_path in font_paths:
                try:
                    if font_path:
                        font_title = ImageFont.truetype(font_path, base_font_size_title)
                        font_text = ImageFont.truetype(font_path, base_font_size_text)
                        font_info = ImageFont.truetype(font_path, base_font_size_info)
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
            
            title_text = "新内容推送"
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
            draw.text((40, y), "【内容】:", fill=text_color, font=font_text)
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

                        
            # 如果内容过长，自动缩小字体以容纳全部内容
            max_lines = 30  # 基准最大行数
            min_font_size = 12  # 最小字体大小
            
            if len(content_lines) > max_lines:
                # 计算缩放比例
                scale_factor = max(min_font_size / base_font_size_text, max_lines / len(content_lines))
                scaled_font_text = int(base_font_size_text * scale_factor)
                scaled_font_info = int(base_font_size_info * scale_factor)
                
                # 重新加载缩放后的字体
                for font_path in font_paths:
                    try:
                        if font_path:
                            font_text = ImageFont.truetype(font_path, scaled_font_text)
                            font_info = ImageFont.truetype(font_path, scaled_font_info)
                            break
                    except:
                        continue
                
                # 重新计算内容行数（字体变小后每行能容纳更多字符）
                content_lines = []
                for para in paragraphs:
                    if para.strip():
                        current_line = ""
                        for char in para:
                            test_line = current_line + char
                            bbox = draw.textbbox((0, 0), test_line, font=font_text)
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
                
                self.log(f"   📏 内容过长({len(content_lines)}行)，字体缩放至 {scaled_font_text}px")

            
            # 绘制全部内容（不再截断）
            # 创建干扰文字的小字体
            try:
                font_noise = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", 16)
            except:
                font_noise = ImageFont.load_default()
            noise_color = (140, 140, 140)  # 极浅色，几乎不可见
            
            # 计算中间位置的两行进行重叠干扰
            total_lines = len([l for l in content_lines if l])  # 非空行总数
            overlap_lines = set()
            for start in range(1, total_lines + 1, 10):
                end = min(start + 9, total_lines)
                # 在当前10行中随机选2行（相邻）
                if end - start + 1 >= 2:
                    overlap_start = random.randint(start, end - 1)
                    overlap_lines.add(overlap_start)
                    overlap_lines.add(overlap_start + 1)
            
            line_count = 0
            for line in content_lines:
                if line:
                    draw.text((40, y), line, fill=text_color, font=font_text, stroke_width=1, stroke_fill=(240, 240, 240))
                    
                    # 行间距：重叠行缩小间距
                    if line_count + 1 in overlap_lines and (line_count + 2) in overlap_lines:
                        y += 16  # 重叠行的第一行后减少间距
                    elif line_count + 1 in overlap_lines and (line_count) in overlap_lines:
                        y += 22  # 重叠行的第二行后恢复正常间距
                    else:
                        y += 22  # 正常行距
                    
                    line_count += 1
                    
                    # 第6行插入干扰文字
                    if line_count == 6:
                        y += 15
                        noise_text = "六便士仅有企业微信推送群，QQ皆为转发，长期稳定推送，请务必添加原作者微信：MK0914666"
                        draw.text((40, y), noise_text, fill=noise_color, font=font_noise)                        
                        y += 35

            # 🆕 如果有提问图片，下载并嵌入
            if question_images and crawler:
                self.log(f"   🖼️ 检测到{len(question_images)}张提问图片，开始嵌入...")
                
                temp_dir = os.path.join(os.path.dirname(__file__), "temp_images")
                os.makedirs(temp_dir, exist_ok=True)
                
                downloaded_images = []
                for img_url in question_images:
                    img_path = self._download_image(img_url, temp_dir)
                    if img_path:
                        downloaded_images.append(img_path)
                
                if downloaded_images:
                    # 计算需要的额外高度
                    max_img_width = img_width - 80
                    total_img_height = 0
                    resized_images = []
                    
                    for img_path in downloaded_images:
                        try:
                            img = Image.open(img_path)
                            # 宽度缩放
                            if img.width > max_img_width:
                                scale = max_img_width / img.width
                                new_height = int(img.height * scale)
                                img = img.resize((max_img_width, new_height), Image.LANCZOS)

                            # 🆕 限制最大高度（压缩图片）
                            max_img_height = 600  # 最大高度限制
                            if img.height > max_img_height:
                                scale = max_img_height / img.height
                                new_width = int(img.width * scale)
                                img = img.resize((new_width, max_img_height), Image.LANCZOS)

                            resized_images.append(img)
                            total_img_height += img.height + 10  # 减少图片间距
                        except Exception as e:
                            self.log(f"   ⚠️ 图片处理失败: {e}")
                    
                    if resized_images:
                        # 计算剩余可用高度
                        remaining_height = img_height - y - 100  # 预留底部声明空间
                        
                        # 如果图片总高度超过剩余空间，按比例缩放
                        if total_img_height > remaining_height:
                            scale = remaining_height / total_img_height
                            for i, img in enumerate(resized_images):
                                new_width = int(img.width * scale)
                                new_height = int(img.height * scale)
                                resized_images[i] = img.resize((new_width, new_height), Image.LANCZOS)
                            self.log(f"   📐 图片已缩放以适应A4格式")
                        
                        # 直接在原图上绘制，不扩展高度
                        draw.text((40, y), "【图片】:", fill=text_color, font=font_text)
                        y += 30
                        
                        for img in resized_images:
                            image.paste(img, (40, y))
                            y += img.height + 10
                        self.log(f"   ✅ 已嵌入{len(resized_images)}张提问图片")
                    
                    # 清理临时图片
                    for img_path in downloaded_images:
                        try:
                            os.remove(img_path)
                        except:
                            pass
            
            # 保存图片到临时目录
            temp_dir = os.path.join(os.path.dirname(__file__), "temp_images")
            os.makedirs(temp_dir, exist_ok=True)
            
            # 生成文件名（使用时间戳避免冲突）
            import time
            timestamp = int(time.time() * 1000)
            image_filename = f"text_msg_{timestamp}.png"
            image_path = os.path.join(temp_dir, image_filename)
            
            # 保存图片
            image.save(image_path, 'PNG', optimize=True)
            
            self.log(f"   ✅ 文本已转换为图片: {image_path}")
            return image_path
            
        except Exception as e:
            self.log(f"   ❌ 文本转图片失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    
    def _handle_text_message(self, index: int, title: str, content: str, author_name: str, 
                   create_time: str, total: int, 
                   question_images: Optional[List[str]] = None,
                   crawler = None) -> bool:
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
                total=total,
                question_images=question_images,
                crawler=crawler
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

