# Share caller credentials only across matching Access audiences

ScreamingFace presents one caller identity and login experience. The Client may reuse one
Cloudflare Access credential for its configured Engine and Scoreboard origins only when both
advertise the same Access issuer and application audience. The dev deployment places both
hostnames in one shared application. Staging and production give the Scoreboard its own
application, scoped to the path `/v1/scores`, so that Engine access does not grant score writes;
there a caller logs in once for each origin (OME-1649). A different audience authenticates
independently and only after an explicit deployment-provided challenge, and that login returns the
browser to the challenged path, because an application scoped to a path leaves the origin root
outside Access. `client.logout()` clears every caller
credential held by that Client. The Client never infers trust from hostname branding alone, guesses
an authentication flow from a plain application 401, or supplies the mesh-owned `X-User-Email`
identity header itself.
