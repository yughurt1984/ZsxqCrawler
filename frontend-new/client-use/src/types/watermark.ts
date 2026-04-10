export interface WatermarkOptions {
    userId: string;
    username: string;
    width?: number;
    height?: number;
    rotate?: number;
    fontSize?: number;
    color?: string;
}

export interface HiddenWatermarkOptions {
    text: string;
    userId: string;
    interval?: number;
}

export interface WatermarkManager {
    applyWatermark(): void;
    destroy(): void;
}
