import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  outputFileTracingRoot: fileURLToPath(new URL(".", import.meta.url)),
  /**
   * Next 15.5+ enables the devtools “segment explorer” by default. It can throw
   * `Could not find the module ... segment-explorer-node.js#SegmentViewNode in the
   * React Client Manifest` during `next dev`, breaking RSC pages (500 + client #418).
   * Disable until upstream fixes land; production `next start` is unaffected.
   */
  experimental: {
    devtoolSegmentExplorer: false,
  },
};

export default nextConfig;
