/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Statischer Export -> reines HTML/JS/JSON in out/ (Netlify, kostenlos, kein Server).
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
