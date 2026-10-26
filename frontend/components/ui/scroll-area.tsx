"use client"

import * as React from "react"
import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area"
import { cn } from "@/lib/models/utils"

function ScrollArea({
  className,
  children,
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.Root>) {
  return (
    <ScrollAreaPrimitive.Root
      data-slot="scroll-area"
      className={cn(
        // ✅ Make sure content fills all available width
        "relative overflow-hidden w-full h-full",
        className
      )}
      {...props}
    >
      {/* ✅ Viewport takes full width — no scrollbar inset */}
      <ScrollAreaPrimitive.Viewport
        data-slot="scroll-area-viewport"
        className="w-full h-full rounded-[inherit]"
      >
        {children}
      </ScrollAreaPrimitive.Viewport>

      {/* ✅ Scrollbar placed at absolute edge */}
      <ScrollBar className="absolute right-0 top-0 h-full" />
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  )
}

function ScrollBar({
  className,
  orientation = "vertical",
  ...props
}: React.ComponentProps<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>) {
  return (
    <ScrollAreaPrimitive.ScrollAreaScrollbar
      data-slot="scroll-area-scrollbar"
      orientation={orientation}
      className={cn(
        "flex touch-none p-px transition-colors select-none bg-transparent",
        orientation === "vertical" &&
          // ✅ Make scrollbar overlay the far-right edge
          "absolute right-0 top-0 w-2.5 h-full",
        orientation === "horizontal" &&
          "absolute bottom-0 left-0 w-full h-2.5 flex-col",
        className
      )}
      {...props}
    >
      <ScrollAreaPrimitive.ScrollAreaThumb
        data-slot="scroll-area-thumb"
        className="bg-border/70 hover:bg-border relative flex-1 rounded-full"
      />
    </ScrollAreaPrimitive.ScrollAreaScrollbar>
  )
}

export { ScrollArea, ScrollBar }
