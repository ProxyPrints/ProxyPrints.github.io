/**
 * This component is a container for the various toast alerts the store needs to raise.
 */

import React from "react";
import Toast from "react-bootstrap/Toast";
import ToastContainer from "react-bootstrap/ToastContainer";

import { Notification, useAppDispatch, useAppSelector } from "@/common/types";
import DisableSSR from "@/components/DisableSSR";
import { RightPaddedIcon } from "@/components/icon";
import {
  clearNotification,
  selectToastsNotifications,
} from "@/store/slices/toastsSlice";

interface NotificationBodyProps {
  notification: Notification;
}

function InfoToastBody({ notification }: NotificationBodyProps) {
  return (
    <>
      <Toast.Header>
        <RightPaddedIcon bootstrapIconName="info-circle" />
        <strong className="me-auto">{notification.name}</strong>
      </Toast.Header>
      {notification.message && (
        <Toast.Body>
          <p>{notification.message}</p>
        </Toast.Body>
      )}
    </>
  );
}

function WarningToastBody({ notification }: NotificationBodyProps) {
  return (
    <>
      <Toast.Header>
        <RightPaddedIcon bootstrapIconName="exclamation-triangle" />
        <strong className="me-auto">{notification.name}</strong>
      </Toast.Header>
      {notification.message && (
        <Toast.Body>
          <p>{notification.message}</p>
        </Toast.Body>
      )}
    </>
  );
}

function ErrorToastBody({ notification }: NotificationBodyProps) {
  return (
    <>
      <Toast.Header>
        <RightPaddedIcon bootstrapIconName="exclamation-circle" />
        <strong className="me-auto">An Error Occurred</strong>
      </Toast.Header>
      <Toast.Body>
        <h6>{notification.name ?? "Unknown Error"}</h6>
        <p>We&apos;re sorry, but an error occurred while handling a request.</p>
        {notification.message != null && (
          <p>
            Error message: <i>{notification.message}</i>
          </p>
        )}
      </Toast.Body>
    </>
  );
}

function NotificationToastBody({ notification }: NotificationBodyProps) {
  switch (notification.level) {
    case "info":
      return <InfoToastBody notification={notification} />;
    case "warning":
      return <WarningToastBody notification={notification} />;
    case "error":
      return <ErrorToastBody notification={notification} />;
  }
}

function NotificationToast() {
  const notifications = useAppSelector(selectToastsNotifications);
  const dispatch = useAppDispatch();

  return (
    <>
      {Object.entries(notifications).map(([key, notification]) => (
        <Toast
          show={notification != null}
          delay={7000}
          autohide
          key={`${key}-toast`}
          onClose={() => dispatch(clearNotification(key))}
        >
          <NotificationToastBody notification={notification} />
        </Toast>
      ))}
    </>
  );
}

export function Toasts() {
  return (
    <DisableSSR>
      <ToastContainer position="bottom-start" className="p-3">
        <NotificationToast />
      </ToastContainer>
    </DisableSSR>
  );
}
