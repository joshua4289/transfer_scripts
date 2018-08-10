import session_func_lite as func

beamlines=['m07','m06', 'm04','m03','m02']
years=['2018']
# identify active sessions
func.poll_ebic(beamlines,years)

