import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // The application does not use next/image. Keeping image optimization off
  // lets the production image omit the vulnerable optional sharp/libvips
  // runtime entirely.
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
