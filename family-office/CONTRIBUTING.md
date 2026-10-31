# Contributing to HVL Family Office

Thank you for your interest in **HVL Family Office**!

## Project Status & Support Expectations

This project is built and maintained primarily for personal household wealth engineering and shared **as-is** with the community under the [PolyForm Noncommercial License 1.0.0](LICENSE).

- **Self-Hosting Support**: We do **not** provide 1-on-1 setup, environment troubleshooting, or IT support for self-hosted deployments. Please use GitHub Discussions for community-to-community setup questions.
- **Bug Reports & Feature Proposals**: Critical bug reports and well-scoped Pull Requests are welcome and reviewed as time permits.
- **Pre-PR Verification**: Before opening a Pull Request, please run:
  ```bash
  python scripts/audit_security_and_data.py
  python -m pytest tests/
  ```
  All contributions must pass the automated security, encryption-at-rest, and zero-PII audit with 0 failures and 0 warnings.
- **Security Disclosures**: If you discover a security or privacy vulnerability, please report it privately to **[privacy@highvelocitylabs.dev](mailto:privacy@highvelocitylabs.dev)** rather than opening a public issue.
- **Commercial Licensing Inquiries**: For commercial licensing outside the scope of the [PolyForm Noncommercial License 1.0.0](LICENSE), contact **[hello@highvelocitylabs.dev](mailto:hello@highvelocitylabs.dev)**.

---

## Contributor License Grant (Outbound + Commercial Rights)

By submitting a Pull Request, patch, or other contribution to this repository, you agree to the following terms:

1. You certify that the contribution is your original work and that you have the legal right to grant this license.
2. You grant **High Velocity Labs** (and the repository owner) a **perpetual, worldwide, non-exclusive, royalty-free, irrevocable license** to use, reproduce, modify, distribute, sublicense, and re-license your contribution under **both noncommercial and commercial terms** (including proprietary or paid SaaS/desktop distributions), without restriction or compensation.
