/**
 * after-pack.cjs — electron-builder afterPack hook.
 *
 * Provides a Windows-host fallback that stamps the Hermes icon + identity onto
 * the packed Windows Hermes.exe via rcedit. Modern electron-builder performs
 * the primary resource edit using pure JavaScript before this hook runs.
 *
 * The fallback only runs on a native Windows builder, avoiding Wine command
 * compatibility problems during macOS cross-builds. It is best-effort so a
 * stamp failure never fails an otherwise-good build.
 *
 * electron-builder passes a context with:
 *   - electronPlatformName: 'win32' | 'darwin' | 'linux'
 *   - appOutDir:            the unpacked app directory for this target
 *   - packager.appInfo.productFilename: the exe basename (e.g. 'Hermes')
 */

const path = require('node:path')

const { stampExeIdentity } = require('./set-exe-identity.cjs')

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'win32' || process.platform !== 'win32') {
    return
  }

  const productName = context.packager?.appInfo?.productFilename || 'Hermes'
  const exe = path.join(context.appOutDir, `${productName}.exe`)
  const desktopRoot = path.resolve(__dirname, '..')

  try {
    await stampExeIdentity(exe, desktopRoot)
  } catch (err) {
    // Never fail the build over a cosmetic stamp.
    console.warn(`[after-pack] exe identity stamp failed (${err.message}); Hermes.exe keeps the stock Electron icon`)
  }
}
