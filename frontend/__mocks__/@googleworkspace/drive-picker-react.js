// Jest manual mock (node_modules mock, auto-applied per
// https://jestjs.io/docs/manual-mocks#mocking-node-modules) for
// @googleworkspace/drive-picker-react - an ESM-only package ("type": "module", no "require"
// export condition) that jest/jsdom can't resolve as-installed on this machine. It's only ever
// referenced as JSX components (DrivePicker/DrivePickerDocsView are custom-element wrappers
// with no interactive behavior worth exercising here) - Footer.tsx became the first jest test
// to render BackendConfig's component tree (via its own "Sources" button, see Footer.tsx's own
// module comment) since GoogleDriveBackendConfig.tsx statically imports GoogleDrivePicker.tsx,
// which statically imports this package - a plain no-op stub is enough for that tree to mount
// without error; nothing here asserts on Google Drive picker behavior itself.
const React = require("react");

function DrivePicker({ children }) {
  return React.createElement(
    "div",
    { "data-testid": "mock-drive-picker" },
    children
  );
}

function DrivePickerDocsView() {
  return null;
}

module.exports = { DrivePicker, DrivePickerDocsView };
