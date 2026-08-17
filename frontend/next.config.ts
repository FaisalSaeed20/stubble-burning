import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  eslint: {
    // Lint issues are surfaced in dev/editor already; don't let them block
    // production builds/deploys.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
