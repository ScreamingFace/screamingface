# Source connection fallback

An availability check tries each validated public address in resolver order until a connection succeeds. Only ConnectError and ConnectTimeout cause fallback. HTTP responses and later read errors are outcomes for the reached server and do not trigger address retries. The original hostname remains in HTTP Host and TLS SNI/certificate validation. Resolve once per redirect hop, validate the full answer set before any connection, and keep all attempts within the existing overall deadline. Mixed public/private answers still refuse the source entirely.
