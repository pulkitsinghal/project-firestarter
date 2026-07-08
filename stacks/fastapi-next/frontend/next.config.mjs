/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_INTERNAL_URL || "http://backend:8000";

const nextConfig = {
  // Browser calls same-origin /api/*; Next proxies to the backend over the
  // compose network so the frontend never needs a public backend URL.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
