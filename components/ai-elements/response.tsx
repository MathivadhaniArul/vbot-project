"use client";

import { cn } from "@/lib/models/utils";
import { memo } from "react";
import dynamic from "next/dynamic";

const Streamdown = dynamic(
  () =>
    import("streamdown").then((mod: any) => {
      console.log("streamdown module resolved:", mod);
      if (mod.Streamdown) return mod.Streamdown;
      if (mod.default && mod.default.Streamdown) return mod.default.Streamdown;
      if (typeof mod.default === "function") return mod.default;
      return () => null;
    }),
  { ssr: false }
);

type ResponseProps = any;

export const Response = memo(
  ({ className, ...props }: ResponseProps) => (
    <Streamdown
      className={cn(
        "size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
        className
      )}
      {...props}
    />
  ),
  (prevProps, nextProps) => prevProps.children === nextProps.children
);

Response.displayName = "Response";
