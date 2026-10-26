"use client";

import { cn } from "@/lib/models/utils";
import { Streamdown } from "streamdown";

type ResponseProps = {
  children?: string;
  className?: string;
};

export const Response = ({ className, children }: ResponseProps) => (
  <Streamdown
    className={cn(
      "size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
      className
    )}
  >
    {children}
  </Streamdown>
);

Response.displayName = "Response";