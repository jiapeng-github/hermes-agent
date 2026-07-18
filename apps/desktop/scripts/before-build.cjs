/**
 * Desktop bundles ship precompiled renderer assets. Returning false here tells
 * electron-builder to skip the node_modules collector/install step, which
 * avoids workspace dependency graph explosions and keeps packaging
 * deterministic across environments. The optional offline runtime is shipped
 * through extraResources rather than the node_modules collector. See
 * `prepare-offline-runtime.cjs` and `electron/main.cjs`.
 */
module.exports = async function beforeBuild() {
  return false
}
