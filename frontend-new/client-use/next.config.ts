import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',  // ← 添加这一行，生成独立可运行文件
  
  // 忽略构建时的错误
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  
  async rewrites() {
    // 根据环境变量确定 API 代理地址
    const apiUrl = process.env.NEXT_PUBLIC_API_PROXY_URL || 'http://localhost:8209';
    return [
      {
        source: '/api/:path*',
        destination: `${apiUrl}/api/:path*`,

      },
    ];
  },
};

export default nextConfig;
