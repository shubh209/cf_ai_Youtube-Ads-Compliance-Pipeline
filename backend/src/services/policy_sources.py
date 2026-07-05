# Registry of live policy URLs to fetch and index.
# Each entry: id (used as blob cache key), platform, url, name.
# platform must be in policy_store._ALLOWED_PLATFORMS.

POLICY_SOURCES: list[dict] = [
    {
        "id": "youtube-ads",
        "platform": "youtube",
        "url": "https://support.google.com/adspolicy/answer/6020955",
        "name": "YouTube Ad Policies",
    },
    {
        "id": "youtube-afcg",
        "platform": "youtube",
        "url": "https://support.google.com/youtube/answer/6162278",
        "name": "YouTube Advertiser-Friendly Content Guidelines",
    },
    {
        "id": "ftc-endorsement",
        "platform": "generic",
        "url": "https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking",
        "name": "FTC Endorsement Guides",
    },
    {
        "id": "tiktok-ads",
        "platform": "tiktok",
        "url": "https://ads.tiktok.com/help/article/tiktok-advertising-policies-industry-entry",
        "name": "TikTok Advertising Policies",
    },
    {
        "id": "meta-ads",
        "platform": "facebook",
        "url": "https://transparency.meta.com/en-us/policies/ad-standards/",
        "name": "Meta Advertising Standards",
    },
]
