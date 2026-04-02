const STORAGE_KEY = 'bunqer-privacy-mode'

let privacyMode = $state(loadPrivacyMode())

function loadPrivacyMode() {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function getPrivacyMode() {
  return privacyMode
}

export function togglePrivacyMode() {
  privacyMode = !privacyMode
  try {
    localStorage.setItem(STORAGE_KEY, String(privacyMode))
  } catch {
    // ignore
  }
}
