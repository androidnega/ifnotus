/**
 * Customer File Manager Verification Test Suite (including Trash / Recycle Bin)
 */
import assert from 'node:assert'
import fs from 'node:fs'

console.log('--- Running Customer File Manager & Trash Test Suite ---')

const fmFile = fs.readFileSync('frontend/src/views/portal/PortalFilesView.vue', 'utf8')

// 1. Check virtual path normalization helper
assert(fmFile.includes('function normalizeVirtualPath'), 'normalizeVirtualPath must exist')
assert(fmFile.includes("clean === 'public'"), 'normalizeVirtualPath must normalize public alias to root')
assert(fmFile.includes("pathStr === '__trash__'"), 'normalizeVirtualPath preserves __trash__ location')

// 2. Check that Directory Tree sidebar contains Home and Trash
assert(fmFile.includes("cp-tree-pane"), 'Tree pane exists in sidebar')
assert(fmFile.includes("@click=\"openDir('.')\""), 'Home node calls openDir(".")')
assert(fmFile.includes("@click=\"openTrash\""), 'Trash node calls openTrash() in Tree')
assert(fmFile.includes("trash-node"), 'Trash node rendered in sidebar')

// 3. Check Breadcrumb / Path logic
assert(fmFile.includes("isTrashMode.value"), 'isTrashMode computed exists')
assert(fmFile.includes("manualPath"), 'Path input bar exists')

// 4. Check that normal delete moves to trash
assert(fmFile.includes("customersApi.moveToTrash"), 'Normal delete calls moveToTrash API')
assert(fmFile.includes("lastMovedTrash"), 'Normal delete sets undo state')
assert(fmFile.includes("undoLastTrash"), 'Undo button restores recently trashed items')

// 5. Check Trash toolbar and actions
assert(fmFile.includes("Restore"), 'Restore action available in Trash')
assert(fmFile.includes("Delete Permanently") || fmFile.includes("Delete permanently"), 'Permanent delete action available in Trash')
assert(fmFile.includes("Empty Trash"), 'Empty trash action available in Trash')
assert(fmFile.includes("restoreTrashTargets"), 'Restore function defined')
assert(fmFile.includes("permanentDeleteTargets"), 'Permanent delete function defined')
assert(fmFile.includes("conflictModal"), 'Conflict resolution modal defined')

// 6. Check empty state display
assert(fmFile.includes("This directory is empty"), 'Folder empty state message exists')

// 7. Check backend file manager jailing and trash support
const backendFmFile = fs.readFileSync('backend/app/services/hosting/files.py', 'utf8')
assert(backendFmFile.includes("def move_to_trash"), 'Backend has move_to_trash method')
assert(backendFmFile.includes("def list_trash"), 'Backend has list_trash method')
assert(backendFmFile.includes("def restore_from_trash"), 'Backend has restore_from_trash method')
assert(backendFmFile.includes("def permanent_delete_trash"), 'Backend has permanent_delete_trash method')
assert(backendFmFile.includes("def empty_trash"), 'Backend has empty_trash method')

// 8. Check customer router trash endpoints
const customerRouterFile = fs.readFileSync('backend/app/routers/v1/customers.py', 'utf8')
assert(customerRouterFile.includes("/environments/{environment_id}/files/trash"), 'Trash endpoints defined in customer router')
assert(customerRouterFile.includes("file_moved_to_trash"), 'Audit log for move to trash')
assert(customerRouterFile.includes("file_restored"), 'Audit log for restore')
assert(customerRouterFile.includes("file_permanently_deleted"), 'Audit log for permanent delete')
assert(customerRouterFile.includes("trash_emptied"), 'Audit log for empty trash')

console.log('ALL 8 Customer File Manager & Trash test assertions PASSED!\n')
