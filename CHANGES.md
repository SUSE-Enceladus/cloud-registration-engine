v2.0.0 (2026-10-08)
===================

- Use cattle-scc-system namespace by default for registration
  secret with an environment variable override REGISTRATION_SECRET_NAMESPACE.
- Pass FQDN as registration URL instead of IP address
- Add hosts record in cluster level CoreDNS with registrtation
  server IP -> FQDN.

v1.1.0 (2026-09-09)
===================

- Drop the environment variable plan info comparison
  + The information is not passing properly from the
    CNAB deployment workflow.

v1.0.0 (2026-07-28)
===================

- First release of Registration Engine

v0.1.0 (2026-06-24)
===================

- Initial version
