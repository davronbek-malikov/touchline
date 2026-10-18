import { Suspense } from "react";

import ChatView from "@/components/ChatView";

export default function AssistantPage() {
  return (
    <Suspense>
      <ChatView />
    </Suspense>
  );
}
