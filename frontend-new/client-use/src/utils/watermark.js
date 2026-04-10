/**
 * 水印工具函数集合
 */

/**
 * 生成零宽字符水印（防复制）
 * @param {string} userId - 用户ID
 * @param {string} platform - 平台名称
 * @returns {string} - 零宽字符水印
 */
export function generateInvisibleWatermark(userId, platform = 'XX平台') {
    const timestamp = new Date().toISOString();
    const watermarkText = `[来源:${platform}|用户:${userId}|时间:${timestamp}]`;
    
    // 将每个字符转为零宽字符编码
    return watermarkText
        .split('')
        .map(char => {
            // 使用零宽字符包裹
            return '\u200B' + char;
        })
        .join('');
}

/**
 * 在文本中插入隐藏干扰文字（CSS隐藏方式）
 * 改进版：在行与行之间插入，不破坏文字连贯性
 * @param {string} html - 原始HTML文本
 * @param {string} userId - 用户ID
 * @param {number} interval - 每隔多少个块级元素插入一次
 * @returns {string} - 包含隐藏水印的HTML
 */
export function insertHiddenWatermark(html, userId, interval = 2) {
    // 简化的干扰文字（更短，不包含时间戳）
    const watermarkText = `请放弃转发本人内容，不要尝试挑战我的能力！`;
    const hiddenSpan = `<span class="hidden-watermark">${watermarkText}</span>`;

    // 在块级元素结束标签后插入
    // 匹配 </p>, </div>, <br>, </li>, </h1>-</h6> 等标签
    const blockEndTags = /(<\/p>|<\/div>|<br\s*\/?>|<\/li>|<\/h[1-6]>)/gi;

    let tagCount = 0;
    const result = html.replace(blockEndTags, (match) => {
        tagCount++;
        // 每隔 interval 个块级元素插入一次干扰文字
        if (tagCount % interval === 0) {
            return match + hiddenSpan;
        }
        return match;
    });

    // 如果没有块级元素，则在换行符处插入
    if (tagCount === 0 && html.includes('\n')) {
        return result.split('\n').join(hiddenSpan + '\n');
    }

    // 如果既没有块级元素也没有换行，在末尾添加一个
    if (tagCount === 0) {
        return result + hiddenSpan;
    }

    return result;
}


/**
 * 生成 Canvas 平铺水印
 * @param {string} userId - 用户ID
 * @param {string} username - 用户名
 * @param {object} options - 配置选项
 * @returns {string} - Base64 图片URL
 */
export function createCanvasWatermark(userId, username, options = {}) {
    const {
        width = 240,
        height = 180,
        rotate = -22,
        fontSize = 16,
        color = 'rgba(0, 0, 0, 0.06)',
        text = `${username} (${userId})`
    } = options;
    
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    
    canvas.width = width;
    canvas.height = height;
    
    // 设置旋转
    ctx.translate(0, 0);
    ctx.rotate(rotate * Math.PI / 180);
    
    // 绘制水印文字
    ctx.font = `${fontSize}px Arial, sans-serif`;
    ctx.fillStyle = color;
    ctx.fillText(text, 20, 80);
    ctx.fillText(new Date().toLocaleDateString('zh-CN'), 20, 105);
    
    return canvas.toDataURL('image/png');
}

/**
 * 应用水印到元素（带防删除功能）
 */
export class WatermarkManager {
    constructor(element, options) {
        this.element = element;
        this.options = options;
        this.observer = null;
        this.timer = null;
        this.isActive = true;
        
        this.init();
    }
    
    init() {
        this.applyWatermark();
        this.setupObserver();
        this.setupTimer();
    }
    
    applyWatermark() {
        if (!this.isActive || !this.element) return;
        
        const { userId, username, color, fontSize } = this.options;
        const watermarkUrl = createCanvasWatermark(userId, username, {
            color,
            fontSize
        });
        
        this.element.style.backgroundImage = `url(${watermarkUrl})`;
        this.element.style.backgroundRepeat = 'repeat';
    }
    
    setupObserver() {
        this.observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && 
                    mutation.attributeName === 'style') {
                    
                    // 检测背景是否被移除
                    if (!this.element.style.backgroundImage) {
                        console.warn('检测到水印被移除，正在恢复...');
                        this.applyWatermark();
                    }
                }
                
                // 检测元素是否被删除
                if (mutation.type === 'childList' && 
                    !document.contains(this.element)) {
                    console.warn('水印容器被删除');
                    this.isActive = false;
                }
            });
        });
        
        this.observer.observe(this.element, {
            attributes: true,
            attributeFilter: ['style'],
            childList: false,
            subtree: false
        });
    }
    
    setupTimer() {
        // 每 30 秒刷新一次水印
        this.timer = setInterval(() => {
            if (this.isActive) {
                this.applyWatermark();
            }
        }, 30000);
    }
    
    destroy() {
        this.isActive = false;
        
        if (this.observer) {
            this.observer.disconnect();
            this.observer = null;
        }
        
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    }
}
