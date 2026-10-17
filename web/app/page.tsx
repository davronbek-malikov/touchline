import { Suspense } from "react";

import SearchChat from "@/components/SearchChat";

export default function SearchPage() {
  return (
    <Suspense>
      <SearchChat />
    </Suspense>
  );
}
