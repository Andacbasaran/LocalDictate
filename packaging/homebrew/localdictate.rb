# Homebrew Cask for LocalDictate (macOS Apple Silicon)
#
# After publishing the v1.0.0 GitHub Release, replace `sha256` with the digest
# for `LocalDictate-v1.0.0-macOS-arm64.dmg` from `SHA256SUMS.txt`.
#
# Install locally:
#   brew install --cask ./packaging/homebrew/localdictate.rb

cask "localdictate" do
  arch arm: "arm64"

  version "1.0.0"
  sha256 "REPLACE_WITH_SHA256_FROM_RELEASE_SHA256SUMS_TXT"

  url "https://github.com/Andacbasaran/LocalDictate/releases/download/v#{version}/LocalDictate-v#{version}-macOS-#{arch}.dmg",
      verified: "github.com/Andacbasaran/LocalDictate/"
  name "LocalDictate"
  desc "100% offline, 0 MB VRAM desktop AI voice dictation studio powered by faster-whisper INT8"
  homepage "https://localdictate.andacbasaran.com"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on macos: ">= :monterey"

  app "LocalDictate.app"

  zap trash: [
    "~/Library/Application Support/LocalDictate",
    "~/Library/LaunchAgents/com.andacbasaran.localdictate.plist",
    "~/Library/Preferences/com.andacbasaran.localdictate.plist",
    "~/Library/Saved Application State/com.andacbasaran.localdictate.savedState",
  ]
end
