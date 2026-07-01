/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_INTERNAL_URL || "http://backend:8000";

const nextConfig = {
  // Browser calls same-origin /api/* and /auth/*; Next proxies both to the
  // backend over the compose network (the auth add-on adds the /auth route).
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/auth/:path*", destination: `${backend}/auth/:path*` },
    ];
  },
};

export default nextConfig;
