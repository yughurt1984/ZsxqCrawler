import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_PROXY_URL || 'http://localhost:8208';
    return [
      {
        source: '/api/:path*',
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;