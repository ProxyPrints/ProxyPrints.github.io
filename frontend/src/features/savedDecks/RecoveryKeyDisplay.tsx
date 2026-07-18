/**
 * Shown exactly once, right after a recovery key is generated (first-save passphrase creation,
 * or the "forgot passphrase" recovery flow reissuing a fresh one) - see
 * docs/proposals/proposal-g-user-accounts-saved-decks.md §8/ZK addendum. Never re-showable
 * after this unmounts; this component itself never persists the key anywhere.
 */

import React, { useState } from "react";
import Button from "react-bootstrap/Button";
import Form from "react-bootstrap/Form";

import { RightPaddedIcon } from "@/components/icon";

interface RecoveryKeyDisplayProps {
  recoveryKeyBase64: string;
  onAcknowledge: () => void;
}

export function RecoveryKeyDisplay({
  recoveryKeyBase64,
  onAcknowledge,
}: RecoveryKeyDisplayProps) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleDownload = () => {
    const blob = new Blob([recoveryKeyBase64], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "saved-deck-recovery-key.txt";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const handleCopy = () => {
    navigator.clipboard
      ?.writeText(recoveryKeyBase64)
      .then(() => setCopied(true));
  };

  const handlePrint = () => {
    const printWindow = window.open("", "_blank");
    if (printWindow == null) {
      return;
    }
    printWindow.document.write(
      `<pre style="font-size: 1.5rem; word-break: break-all; white-space: pre-wrap;">${recoveryKeyBase64}</pre>`
    );
    printWindow.document.close();
    printWindow.print();
  };

  return (
    <>
      <p>
        <strong>
          Store this somewhere safe - it is the ONLY way to recover your decks
          if you forget your passphrase.
        </strong>{" "}
        It won&apos;t be shown again after you close this dialog.
      </p>
      <pre
        data-testid="recovery-key-text"
        className="p-2 bg-light border rounded"
        style={{ wordBreak: "break-all", whiteSpace: "pre-wrap" }}
      >
        {recoveryKeyBase64}
      </pre>
      <div className="d-flex gap-2 mb-3">
        <Button variant="secondary" size="sm" onClick={handleDownload}>
          <RightPaddedIcon bootstrapIconName="download" /> Download
        </Button>
        <Button variant="secondary" size="sm" onClick={handleCopy}>
          <RightPaddedIcon bootstrapIconName="clipboard" />{" "}
          {copied ? "Copied!" : "Copy"}
        </Button>
        <Button variant="secondary" size="sm" onClick={handlePrint}>
          <RightPaddedIcon bootstrapIconName="printer" /> Print
        </Button>
      </div>
      <Form.Check
        type="checkbox"
        id="recovery-key-acknowledge"
        label="I've saved this recovery key somewhere safe"
        checked={acknowledged}
        onChange={(event) => setAcknowledged(event.target.checked)}
      />
      <Button
        className="mt-3"
        variant="primary"
        disabled={!acknowledged}
        onClick={onAcknowledge}
        data-testid="recovery-key-continue"
      >
        Continue
      </Button>
    </>
  );
}
