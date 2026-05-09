/** @type {import('next').NextConfig} */
const isProd = process.env.NODE_ENV === 'production';
const basePath = isProd ? '/paperradar' : '';

const nextConfig = {
  reactStrictMode: true,
  output: 'export',
  trailingSlash: false,
  basePath,
  assetPrefix: basePath || undefined,
  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
