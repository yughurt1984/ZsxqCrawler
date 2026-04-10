'use client';

import React, { useEffect, useRef, useMemo } from 'react';
import {
    WatermarkManager,
    insertHiddenWatermark,
    generateInvisibleWatermark
} from '@/utils/watermark.js';

interface WatermarkCardProps {
    children?: React.ReactNode;
    content?: string;
    userId: string;
    username: string;
    hiddenInterval?: number;
    watermarkColor?: string;
    watermarkFontSize?: number;
    className?: string;
    style?: React.CSSProperties; // 新增
}

export default function WatermarkCard({
    children,
    content = '',
    userId,
    username,
    hiddenInterval = 50,
    watermarkColor = 'rgba(0, 0, 0, 0.06)',
    watermarkFontSize = 16,
    className = '',
    style = {} // 新增
}: WatermarkCardProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const managerRef = useRef<WatermarkManager | null>(null);

    // 处理内容（添加隐藏干扰文字）
    const processedContent = useMemo(() => {
        if (!content) return '';

        // 方式1：CSS 隐藏干扰文字
        const withHiddenText = insertHiddenWatermark(
            content,
            userId,
            hiddenInterval
        );

        // 方式2：零宽字符水印（可选，更隐蔽）
        const zeroWidthWatermark = generateInvisibleWatermark(userId);

        return zeroWidthWatermark + withHiddenText;
    }, [content, userId, hiddenInterval]);

    // 初始化水印
    useEffect(() => {
        if (containerRef.current) {
            managerRef.current = new WatermarkManager(containerRef.current, {
                userId,
                username,
                color: watermarkColor,
                fontSize: watermarkFontSize
            });
        }

        return () => {
            if (managerRef.current) {
                managerRef.current.destroy();
            }
        };
    }, [userId, username, watermarkColor, watermarkFontSize]);

    return (
        <div
            ref={containerRef}
            className={`watermark-card ${className}`}
            style={{
                position: 'relative',
                padding: '24px',
                backgroundColor: '#ffffff',
                borderRadius: '12px',
                boxShadow: '0 2px 12px rgba(0, 0, 0, 0.08)',
                minHeight: '200px',
                ...style // 合并自定义样式
            }}
        >
            <div className="content-wrapper" style={{ position: 'relative', zIndex: 1 }}>
                {content && (
                    <div
                        className="content-text"
                        dangerouslySetInnerHTML={{ __html: processedContent }}
                        style={{
                            wordBreak: 'break-word',
                            whiteSpace: 'pre-wrap',
                            lineHeight: 1.8,
                            color: '#333'
                        }}
                    />
                )}
                {children}
            </div>

            {/* 内联样式：隐藏干扰文字 */}
            <style jsx>{`
                .watermark-card :global(.hidden-watermark) {
                    opacity: 0;
                    font-size: 1px;
                    user-select: text;
                    display: inline;
                    line-height: 0;
                    color: transparent;
                }
            `}</style>
        </div>
    );
}
