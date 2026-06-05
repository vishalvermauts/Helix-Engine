trigger_keywords: [security, scan, scanner, secret, vulnerability, vulnerabilities, github_scanner, audit]

# Security Agent Guidelines

When generating agents that scan for security vulnerabilities or secrets, adhere to the following best practices to avoid common implementation bugs:

1. **Secret Scanning:** DO NOT use basic regex or `git grep`. ALWAYS use Gitleaks (`gitleaks detect --source .`) for proper history-aware secret scanning. Be aware that scanning only the working tree misses deleted secrets in history.
2. **Python Static Analysis (Bandit):** 
   - DO NOT use fake flags like `--severity-level`. To filter for medium severity and higher, use `-ll`.
   - ALWAYS use JSON output format (`-f json`) and parse the output using `json.loads(stdout)` instead of fragile text parsing.
3. **Node.js Analysis (npm audit):** 
   - DO NOT check for just `package.json`. `npm audit` requires a lockfile. ALWAYS check for `package-lock.json` before running `npm audit`. Fallback to `yarn.lock` and `yarn audit` if needed.
   - ALWAYS use JSON output format (`--json`) and parse the metadata to count vulnerabilities (e.g., `data.get("metadata", {}).get("vulnerabilities", {}).get("high", 0)`). DO NOT use substring matching (like `.count("high")`) on the raw stdout.
4. **State Management:** When writing object-oriented scanner classes, ensure that any internal state tracking vulnerabilities (e.g., `self._summary`) is explicitly cleared/reset at the beginning of the `run()` method so counts don't accumulate across multiple runs.
5. **Data Aggregation:** Ensure that findings parsed from all individual tools (Bandit, npm, bundler) correctly flow into and update the global executive summary totals.
6. **Exception Trapping:** Subprocess calls often fail if the binary is missing or returns a non-zero exit code. Always wrap these in `try/except subprocess.CalledProcessError`.