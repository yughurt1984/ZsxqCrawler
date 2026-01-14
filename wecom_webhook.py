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
        print(message)  # 输出到控制台
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
                
                 # ========== 4. 分支3: 纯文本推送 ==========
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
        """获取PDF输出目录"""
        path_manager = get_db_path_manager()
        group_dir = path_manager.get_group_dir(crawler.group_id)
        
        # 根据下载配置决定PDF保存位置
        config = load_config()
        download_config = config.get('download', {})
        download_dir = download_config.get('dir', 'downloads')
        
        if download_dir == "downloads":
            # 使用默认目录结构：group_dir/pdfs
            return os.path.join(group_dir, 'pdfs')
        else:
            # 使用自定义目录：download_dir/group_{group_id}/pdfs
            return os.path.join(download_dir, f"group_{crawler.group_id}", 'pdfs')
    
    def _handle_article_pdf(self, index: int, article_url: str, title: str, crawler, total: int) -> bool:
        """处理文章PDF转换和推送（分支1）"""
        try:
            self.log(f"📄 第{index}/{total}条：检测到文章链接，开始转换PDF...")
            
            # 获取PDF输出目录
            pdf_output_dir = self._get_pdf_output_dir(crawler)
            
            # 转换PDF
            pdf_path = crawler.convert_url_to_pdf(article_url, pdf_output_dir, title)
            
            if pdf_path:
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
