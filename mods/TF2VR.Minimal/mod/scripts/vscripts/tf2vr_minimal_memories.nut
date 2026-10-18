global function TF2VR_CheckDynamicMemory
global function TF2VR_PrepareMemory

void function TF2VR_CheckDynamicMemory( int unused, vector headOrigin ) {}

// the plugin requires a camera to be published; -1 is the "map records no memories" answer
void function TF2VR_PrepareMemory( int reusePilot, int event, int btView )
{
	TF2VR_SetMemoryCamera( -1, 0, 0, <0,0,0> )
}
