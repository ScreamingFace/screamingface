import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // WHY "standalone" and not the studio frontend's "export": this app is a BFF. Every call to
  // aigateway's /v1/admin surface happens server-side, so that the browser never holds the admin
  // API's address and X-User-Email never has to survive a round trip through client code. A static
  // export has no server and could not do that.
  output: "standalone",
  experimental: {
    serverActions: {
      // Cache-snapshot uploads travel through a server action as multipart FormData. Next's default
      // 1 MB cap would reject a real snapshot (tens of MB) with a raw runtime error instead of the
      // gateway's clean 413. Set to the gateway's own cap (AIGW_CACHE_UPLOAD_MAX_BYTES, 256 MB) so
      // the gateway stays the authoritative size gate.
      bodySizeLimit: "256mb",
    },
  },
};

export default nextConfig;
