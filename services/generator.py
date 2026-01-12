import re
from typing import List, Dict
from models import Channel

class M3UGenerator:
    @staticmethod
    def filter_channels(channels: List[Channel], regex_pattern: str, keywords: List[dict] = None) -> List[Channel]:
        # keywords expected format: [{"value": "keyword", "group": "target_group"}]
        filtered = []
        
        # 1. Keyword filtering (OR logic) with Group Assignment
        if keywords:
            # Create a set to avoid duplicates if a channel matches multiple keywords (priority to first match)
            seen_ids = set()
            
            for k_obj in keywords:
                k_val = k_obj.get("value", "").lower()
                target_group = k_obj.get("group", "").strip()
                if not k_val:
                    continue
                    
                for c in channels:
                    if c.id in seen_ids:
                        continue
                        
                    if k_val in c.name.lower():
                        # Found a match
                        # Create a shallow copy to avoid mutating original list/db objects
                        # We use simple object creation or verify if model_copy works (SQLModel)
                        # For SQLModel, model_copy() is standard pydantic
                        c_copy = c.model_copy()
                        
                        if target_group:
                            c_copy.group = target_group
                            
                        filtered.append(c_copy)
                        seen_ids.add(c.id)
        else:
            # If no keywords, start with all channels (but we usually use this for filtering)
            filtered = [c.model_copy() for c in channels]
            
        # 2. Regex filtering (Final pass)
        if regex_pattern and regex_pattern != ".*":
            try:
                pattern = re.compile(regex_pattern, re.IGNORECASE)
                filtered = [c for c in filtered if pattern.search(c.name)]
            except re.error:
                pass # Pattern invalid, skip regex pass
                
        return filtered

    @staticmethod
    def propagate_logos(channels: List[Channel]) -> List[Channel]:
        """
        Fill missing logos by finding a valid logo from another channel 
        with the same tvg-id (or name if tvg-id is missing).
        """
        # Group by identifier (tvg-id or name)
        # We want to identify channels that SHOULD be the same.
        # Logic: If c1.tvg_id == c2.tvg_id, they are same.
        # If c1.name == c2.name (and no tvg_id), they are same.
        
        # Build map: ID -> valid_logo
        id_logo_map = {}
        
        # 1. Collect Logos
        for c in channels:
            if c.logo:
                key = c.tvg_id if c.tvg_id else c.name
                if key and key not in id_logo_map:
                    id_logo_map[key] = c.logo
        
        # 2. Apply Logos
        # We iterate and modify in place (or returned list)
        for c in channels:
            if not c.logo:
                key = c.tvg_id if c.tvg_id else c.name
                if key and key in id_logo_map:
                    c.logo = id_logo_map[key]
                    
        return channels

    @staticmethod
    def generate_m3u(channels: List[Channel], sub_map: Dict[int, str] = None, epg_url: str = None, include_suffix: bool = True) -> str:
        # Auto-fill logos
        channels = M3UGenerator.propagate_logos(channels)

        header = "#EXTM3U"
        if epg_url:
            header += f' x-tvg-url="{epg_url}"'
        lines = [header]
        
        for c in channels:
            # Append source name if available and requested
            source_tag = f" ({sub_map[c.subscription_id]})" if include_suffix and sub_map and c.subscription_id in sub_map else ""
            display_name = f"{c.name}{source_tag}"
            
            # Metadata: logo, tvg-id, and tvg-name (preserve original name for EPG)
            logo_attr = f' tvg-logo="{c.logo or ""}"'
            tvg_id_attr = f' tvg-id="{c.tvg_id or ""}"'
            tvg_name_attr = f' tvg-name="{c.name}"'
            group_attr = f' group-title="{c.group or "Default"}"'
            
            inf = f'#EXTINF:-1{tvg_id_attr}{tvg_name_attr}{logo_attr}{group_attr},{display_name}'
            lines.append(inf)
            lines.append(c.url)
        return "\n".join(lines)
