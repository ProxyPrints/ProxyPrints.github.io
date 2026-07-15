/**
 * The moderator-only Moderation tab (docs/features/moderation.md), mounted from whatsthat.tsx
 * alongside the ordinary question feed - see that file for the outer Tab.Container this
 * nests inside (same react-bootstrap Tab.Container/Nav/Tab.Pane idiom the pre-redesign
 * printing/artist/tag tab switcher used).
 *
 * Two sub-tabs: Reports (ReportsPanel.tsx - pending sensitive-tag approvals from user
 * reports) and Drives (DrivesPanel.tsx - browse/remove Source rows and individual cards).
 * These used to be one and the same thing (report review briefly lived inline in the
 * unified question feed as a moderator-only "tier 3" - see cardpicker/question_feed.py's
 * docstring for why that was reverted) - splitting them into an explicit switch means a
 * pending report never displaces a moderator's ordinary tagging work, and drive management
 * (which has nothing to do with reports) gets its own home instead of being bolted on.
 */

import React, { useState } from "react";
import Nav from "react-bootstrap/Nav";
import Tab from "react-bootstrap/Tab";

import { DrivesPanel } from "@/features/moderation/DrivesPanel";
import { ReportsPanel } from "@/features/moderation/ReportsPanel";

type ModerationSubTab = "reports" | "drives";

export function ModerationTab() {
  const [activeSubTab, setActiveSubTab] = useState<ModerationSubTab>("reports");

  return (
    <Tab.Container
      activeKey={activeSubTab}
      onSelect={(key) => {
        if (key) setActiveSubTab(key as ModerationSubTab);
      }}
    >
      <Nav variant="pills" className="mb-3">
        <Nav.Item>
          <Nav.Link eventKey="reports">Reports</Nav.Link>
        </Nav.Item>
        <Nav.Item>
          <Nav.Link eventKey="drives">Drives</Nav.Link>
        </Nav.Item>
      </Nav>
      <Tab.Content>
        {/* mountOnEnter/unmountOnExit on both - neither should keep fetching/paginating in
            the background while the moderator is looking at the other one (same rationale as
            the pre-redesign printing/artist/tag switcher this mirrors). */}
        <Tab.Pane eventKey="reports" mountOnEnter unmountOnExit>
          <ReportsPanel />
        </Tab.Pane>
        <Tab.Pane eventKey="drives" mountOnEnter unmountOnExit>
          <DrivesPanel />
        </Tab.Pane>
      </Tab.Content>
    </Tab.Container>
  );
}
