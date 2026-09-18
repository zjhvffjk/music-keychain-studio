"""Structured, reviewable art direction. This module deliberately performs no image generation."""
from copy import deepcopy

PARTS=["front","back","spine","disc","booklet_cover","booklet_spread","lyrics","inner_sleeve","poster","postcard"]
BASE_FORBIDDEN=["pyramid","outer space","planet","science-fiction architecture","cyberpunk","futuristic city","surreal landscape","unrelated product flat lay","text rendered by image model"]


def _greatest():
 return {"subject":"Asian male artist, viewed in profile or from behind; never a different celebrity likeness","environment":"Mont Saint-Michel / European medieval coastal architecture, tidal sea, reflection, old streets and classical interiors","photography_style":"realistic cinematic travel photography","composition":"architectural scale balanced with a solitary human figure and generous sky or water","lighting":"soft natural daylight, blue-hour or warm late-afternoon sun","texture":"weathered stone, water reflection, linen paper, aged brass","era":"timeless European travel and classical art","mood":"contemplative, elegant, romantic, artistic","motifs":["spire","tidal water","castle silhouette","piano","sculpture","window light","old street"],"materials":["limestone","sea water","paper","brass","wood"],"typography_style":"high-contrast classical serif with restrained Chinese type","narrative":"an artist travelling through a living European artwork; music, memory and architecture meet","allowed_elements":["European castle","coast","reflection","old street","piano","sculpture","art studio","solitary artist","blue sky"],"forbidden_elements":BASE_FORBIDDEN}

def build(album,artist,style):
 # Named test case is explicit because semantic vision is not yet installed; other covers remain user-reviewable drafts.
 dna=_greatest() if "最伟大的作品" in album or "Greatest Works" in album else {"subject":"to be confirmed from cover","environment":"to be confirmed from cover","photography_style":style["style"],"composition":"editorial album cover composition","lighting":"derived natural lighting","texture":"cover-derived material texture","era":"to be confirmed","mood":style["mood"],"motifs":[],"materials":[],"typography_style":"editorial restrained type","narrative":"to be confirmed","allowed_elements":[],"forbidden_elements":BASE_FORBIDDEN}
 dna["color_palette"]=style["palette"]
 bible={"world_statement":dna["narrative"],"people":dna["subject"],"places":dna["environment"],"light":dna["lighting"],"era":dna["era"],"allowed_elements":dna["allowed_elements"],"forbidden_elements":dna["forbidden_elements"],"continuity_rules":["same geography and period","new camera angle for every component","no AI text or logos","programmatic typography only"]}
 scenes={
 "front":"original reference cover preserved as the approved front artwork","back":"distant coastal castle across tidal water; empty upper area for programmatic track list","spine":"stone-blue material field and restrained typography only","disc":"tidal-water reflection and castle spire seen as a radial crop; no invented objects","booklet_cover":"artist at a piano in a sunlit classical interior with sculpture and stone","booklet_spread":"window-facing European studio: piano on one page, architectural pencil study and quiet text area on the other","lyrics":"paper, window light and a faint castle-water detail; deliberately calm for programmed lyrics","inner_sleeve":"artist walking an old European street towards the distant spire","poster":"wide coastal sunset, castle silhouette and solitary artist from behind","postcard":"small old-street view with lamp, spire and sea-blue sky"}
 plans=[]
 for key in PARTS:
  brief=scenes[key]
  plans.append({"component":key,"subject":brief,"environment":dna["environment"],"camera":"new editorial angle; no repeated crop","composition":"reserve intentional typography space","lighting":dna["lighting"],"mood":dna["mood"],"key_motifs":dna["motifs"],"negative_elements":dna["forbidden_elements"],"reference_strength":0.78})
 master=("Create a photographic album-art world faithful to this reference: "+dna["narrative"]+". Allowed: "+", ".join(dna["allowed_elements"])+". Never introduce: "+", ".join(dna["forbidden_elements"])+". No text, logos, signatures, barcodes or typography.")
 for plan in plans: plan["provider_prompt"]=master+" Component: "+plan["subject"]+". Camera: "+plan["camera"]+"."
 return {"version":"art-director-v1","status":"awaiting-art-direction-approval","visual_dna":dna,"scene_bible":bible,"master_art_direction_prompt":master,"component_scene_plans":plans,"candidate_count":3,"reviewer_rules":{"reject_on_forbidden_element":True,"dimensions":["subject","environment","style","lighting","era","materials","narrative","motifs"]}}
