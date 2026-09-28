import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Local development is commonly opened via loopback or this computer's LAN
  // address. Without this, Next 16 blocks client dev assets/HMR and client
  // components such as the episode panel never hydrate.
  allowedDevOrigins: ["127.0.0.1", "192.168.1.156"],
  turbopack: { root: __dirname },
  images: {
    unoptimized: true,
    remotePatterns: [
      { protocol: "https", hostname: "s4.anilist.co", pathname: "/file/**" },
      { protocol: "https", hostname: "s3.anilist.co", pathname: "/file/**" },
    ],
  },
};

export default nextConfig;
