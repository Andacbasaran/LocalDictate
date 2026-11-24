# SignPath.io Free Open-Source Code Signing Guide

[SignPath Foundation](https://signpath.org/) provides **free, trusted EV/OV Authenticode code signing** for eligible open-source projects via GitHub Actions, eliminating Windows SmartScreen "Unknown Publisher" warnings.

## Activation Steps for LocalDictate

1. **Apply to the SignPath Open Source Program** with `https://github.com/Andacbasaran/LocalDictate` (`LICENSE`, `SECURITY.md`, and `.github/workflows/release.yml` are already in place).
2. **Create SignPath Project:**
   - Organization slug: `localdictate`
   - Project slug: `localdictate`
   - Signing policy: `release-signing`
3. **Add Repository Secrets:**
   - `SIGNPATH_API_TOKEN`
   - `SIGNPATH_ORGANIZATION_ID`
4. **Enable the SignPath Step in `.github/workflows/release.yml`:**
   ```yaml
   - name: Submit Windows artifacts to SignPath.io
     if: startsWith(github.ref, 'refs/tags/v') && secrets.SIGNPATH_API_TOKEN != ''
     uses: signpath/github-action-submit-signing-request@v1
     with:
       api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
       organization-id: ${{ secrets.SIGNPATH_ORGANIZATION_ID }}
       project-slug: localdictate
       artifact-configuration-slug: release-zip
       signing-policy-slug: release-signing
       github-artifact-id: ${{ steps.upload.outputs.artifact-id }}
       wait-for-completion: true
       output-artifact-directory: signed_out
   ```
5. **Recompute `SHA256SUMS.txt`** from the signed binaries before publishing the GitHub Release.
