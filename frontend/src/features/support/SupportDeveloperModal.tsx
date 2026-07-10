import React from "react";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";

import { ProjectName } from "@/common/constants";
import { Coffee } from "@/components/Coffee";
import { MakePlayingCardsLink } from "@/components/MakePlayingCardsLink";

interface SupportDeveloperModalProps {
  show: boolean;
  handleClose: {
    (): void;
    (event: React.MouseEvent<HTMLButtonElement, MouseEvent>): void;
  };
}

export function SupportDeveloperModal({
  show,
  handleClose,
}: SupportDeveloperModalProps) {
  return (
    <Modal scrollable show={show} onHide={handleClose} size="lg">
      <Modal.Header closeButton>
        <Modal.Title>Support the Developer</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <h4>A bit about the developer</h4>
        <p>
          ProxyPrints is built on MPC Autofill, an open-source project created and maintained by chilli_axe. All the heavy lifting — the card search engine, the project editor, and the desktop tool that automates your MakePlayingCards order — comes from that project.
If ProxyPrints is useful to you, consider supporting the original developer on Patreon, or starring the project on GitHub.
        </p>
        <p>Any donation goes towards:</p>
        <ul>
          <li>Fuelling his coffee addiction, and</li>
          <li>
            Allowing him to spend more time developing and improving this project
            for us all. Several large features are in the pipeline that
            He&apos;s excited to share when they&apos;re ready!
          </li>
        </ul>
        <hr />
        <Coffee />
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={handleClose}>
          Close
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
