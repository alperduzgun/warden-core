# Warden Core Release Roadmap

## Pending Critical Task: Binary Distribution (Wheels)

**Status:** Planned / Postponed
**Priority:** Critical for End-User Adoption

### The Problem
The current GitHub Actions CI (`.github/workflows/ci.yml`) successfully builds and authenticates the project because the `ubuntu-latest` runner **pre-installs Rust**.

However, end-users running `pip install warden-core` will **FAIL** if they do not have a Rust compiler installed locally. Pip attempts to build the Rust extension from source (sdist), which requires `cargo` and `rustc`.

### The Solution: `cibuildwheel`
To fix this, we need to create a new GitHub Actions workflow (e.g., `.github/workflows/release.yml`) that uses `cibuildwheel`. This tool builds pre-compiled binary wheels for all major platforms (Windows, macOS, Linux) and uploads them to PyPI.

With binary wheels, users can just run `pip install warden-core` and it works immediately, with zero dependencies on Rust.

### Implementation Steps

1.  **Create Workflow File:** `.github/workflows/release.yml`
2.  **Configure `cibuildwheel`:**
    ```yaml
    jobs:
      build_wheels:
        name: Build wheels on ${{ matrix.os }}
        runs-on: ${{ matrix.os }}
        strategy:
          matrix:
            os: [ubuntu-latest, windows-latest, macos-latest]
        steps:
          - uses: actions/checkout@v4
          - name: Build wheels
            uses: pypa/cibuildwheel@v2.16.2
          - uses: actions/upload-artifact@v4
            with:
               path: ./wheelhouse/*.whl
    ```
3.  **Publish:** Add a job to twine upload these wheels to PyPI upon a new Release Tag (e.g., `v1.0.0`).

### Reference
*   [cibuildwheel Documentation](https://cibuildwheel.readthedocs.io/en/stable/)
*   [Setuptools Rust Binding](https://github.com/PyO3/setuptools-rust)
