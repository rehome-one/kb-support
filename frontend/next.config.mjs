/** @type {import('next').NextConfig} */
const nextConfig = {
  // standalone output для компактного Docker-образа (E2).
  output: "standalone",
  reactStrictMode: true,
};

export default nextConfig;
