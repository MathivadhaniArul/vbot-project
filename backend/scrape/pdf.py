from urllib.parse import quote

title = "Hackathon Registration Deadline"
details = "VIT Hackathon Registration closes"
location = "VIT Vellore"

start = "20260615T173000Z"
end = "20260615T180000Z"

print("Title:", quote(title))
print("Details:", quote(details))
print("Location:", quote(location))
print("Dates:", f"{start}/{end}")

url = (
    "https://calendar.google.com/calendar/render?action=TEMPLATE"
    f"&text={quote(title)}"
    f"&dates={start}/{end}"
    f"&details={quote(details)}"
    f"&location={quote(location)}"
)

print(url)